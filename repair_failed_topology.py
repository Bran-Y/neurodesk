"""Non-destructive FS5.3 topology retry in a separate subjects directory."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


def write_state(folder, **updates):
    path = folder / 'repair_status.json'
    state = json.loads(path.read_text()) if path.exists() else {}
    state.update(updates, updated_utc=datetime.now(timezone.utc).isoformat())
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(path)


def prepare(source, destination):
    import nibabel as nib
    import numpy as np
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination == source or source in destination.parents:
        raise ValueError('Repair destination must be new and outside the original subject')
    stamp = (source / 'scripts/build-stamp.txt').read_text()
    if not re.search(r'(?<!\d)5\.3\.0(?!\d)', stamp):
        raise ValueError('Expected an original FreeSurfer 5.3.0 subject')
    if (source / 'scripts/recon-all.done').exists():
        raise ValueError('Refusing to repair an already completed reconstruction')
    if subprocess.run(['pgrep', '-x', 'recon-all'], capture_output=True).returncode == 0:
        raise RuntimeError('Another recon-all is running; avoid concurrent reconstruction')
    diagnostics = []
    for name in ('rh.orig.nofix', 'rh.smoothwm.nofix', 'rh.inflated.nofix', 'rh.qsphere.nofix'):
        path = source / 'surf' / name
        vertices, faces = nib.freesurfer.read_geometry(path)
        if (not np.isfinite(vertices).all() or not len(faces) or faces.min() < 0 or
                faces.max() >= len(vertices) or (np.bincount(faces.ravel(), minlength=len(vertices)) == 0).any()):
            raise ValueError('Invalid upstream geometry: ' + name)
        diagnostics.append(dict(file=name, vertices=len(vertices), faces=len(faces),
                                sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    required = sum(f.stat().st_size for f in source.rglob('*') if f.is_file()) + 8 * 1024**3
    if shutil.disk_usage(source).free < required:
        raise RuntimeError('Insufficient disk space for an independent copy and reconstruction')
    destination.mkdir(parents=True)
    copied = destination / 'subjects' / source.name
    shutil.copytree(source, copied, symlinks=False)
    # Only stale locks in the copy are removed; original failure evidence remains intact.
    for lock in (copied / 'scripts').glob('IsRunning*'):
        lock.unlink()
    commands = ['set -euo pipefail', 'ml freesurfer/5.3.0',
                shlex.join(['recon-all', '-sd', str(copied.parent), '-s', source.name,
                            '-autorecon2-wm', '-autorecon3', '-no-fix-with-ga'])]
    (destination / 'retry.sh').write_text('\n'.join(commands) + '\n')
    write_state(destination, subject_id=source.name, original_subject=str(source),
                repair_subject=str(copied), status='prepared', original_unchanged=True,
                upstream_mesh_checks=diagnostics, processing_version='5.3.0',
                strategy='Regenerate WM surfaces and downstream outputs without genetic algorithm; topology fixing remains enabled',
                documentation='https://surfer.nmr.mgh.harvard.edu/fswiki/recon-all',
                promoted_to_workflow=False, human_qc_accepted=False)
    return destination


def run(folder):
    folder = Path(folder).resolve()
    state = json.loads((folder / 'repair_status.json').read_text())
    write_state(folder, status='running')
    try:
        with (folder / 'reconstruction.log').open('xb') as log:
            subprocess.run(['bash', '-lc', (folder / 'retry.sh').read_text()],
                           stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, check=True)
        subject = Path(state['repair_subject'])
        for name in ('scripts/recon-all.done', 'stats/aseg.stats', 'stats/lh.aparc.stats',
                     'stats/rh.aparc.stats', 'surf/rh.white', 'surf/rh.pial'):
            if not (subject / name).is_file():
                raise RuntimeError('Missing repaired output: ' + name)
        write_state(folder, status='completed_requires_visual_qc')
    except Exception as exc:
        write_state(folder, status='failed', error=str(exc))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    if args.run:
        run(args.run)
    else:
        folder = prepare(args.source, args.destination)
        with (folder / 'launcher.log').open('xb') as log:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--run', str(folder)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        write_state(folder, launcher_pid=child.pid)
        print('REPAIR_LAUNCHED', child.pid, folder)
