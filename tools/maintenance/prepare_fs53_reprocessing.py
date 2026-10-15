"""Plan isolated FreeSurfer 5.3 runs; launch only when explicitly requested."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess


def prepare(fs_home, input_dir, output_dir, subjects, launch=False):
    fs_home, input_dir, output_dir = map(lambda p: Path(p).resolve(), (fs_home, input_dir, output_dir))
    stamp = (fs_home / 'build-stamp.txt').read_text().strip()
    if not re.search(r'(?<!\d)5\.3\.0(?!\d)', stamp):
        raise ValueError('Selected installation is not FreeSurfer 5.3.0: ' + stamp)
    setup = fs_home / 'SetUpFreeSurfer.sh'
    if not setup.exists():
        raise FileNotFoundError(setup)
    plans = []
    for sid in subjects:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', sid):
            raise ValueError('Invalid subject identifier')
        source = input_dir / (sid + '_T1w.nii.gz')
        if not source.exists():
            raise FileNotFoundError(source)
        if (output_dir / sid).exists():
            raise FileExistsError('Use a fresh output root; refusing to overwrite ' + str(output_dir / sid))
        command = ('export FREESURFER_HOME=' + shlex.quote(str(fs_home)) + '; source ' + shlex.quote(str(setup)) +
                   ' && recon-all -sd ' + shlex.quote(str(output_dir)) + ' -s ' + shlex.quote(sid) +
                   ' -i ' + shlex.quote(str(source)) + ' -all')
        plans.append({'subject_id': sid, 'input': str(source), 'command': command,
                      'expected_image': str(output_dir / sid / 'mri/brain.mgz'), 'build_stamp': stamp})
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / 'fs53_reprocessing_plan.json'
    if manifest.exists():
        raise FileExistsError('A plan already exists in this output directory')
    manifest.write_text(json.dumps(plans, indent=2) + '\n')
    if launch:
        # One detached serial queue prevents four full reconstructions exhausting RAM.
        command = 'set -e\n' + '\n'.join(p['command'] for p in plans)
        with (output_dir / 'reprocessing.log').open('ab') as log:
            process = subprocess.Popen(['bash', '-lc', command], stdout=log, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
        (output_dir / 'queue.pid').write_text(str(process.pid))
    return plans


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--fs-home', required=True)
    p.add_argument('--input-dir', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--subjects', nargs='+', required=True)
    p.add_argument('--launch', action='store_true')
    a = p.parse_args()
    print(json.dumps(prepare(a.fs_home, a.input_dir, a.output_dir, a.subjects, a.launch), indent=2))
