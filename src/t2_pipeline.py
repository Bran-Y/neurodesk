"""T2-only research preprocessing. Never feeds SynthSeg volumes to Potvin."""
from pathlib import Path
import base64
import hashlib
import html
import io
import json
import re
import shlex
import subprocess

MODULE = 'freesurfer/8.2.0'
ARTIFACTS = ('brain.nii.gz', 'brain_mask.nii.gz', 'segmentation.nii.gz',
             'resampled.nii.gz', 'volumes.csv', 'qc.csv')


def cases(config):
    import pandas as pd
    if config.get('modality') != 'T2':
        raise ValueError('This branch accepts declared T2 only')
    frame = pd.read_csv(config['metadata_csv'], dtype=str).fillna('')
    if frame.empty or not {'subject_id', 'image_path', 'modality', 'modality_confirmed'}.issubset(frame):
        raise ValueError('Missing T2 input metadata')
    if frame.subject_id.duplicated().any():
        raise ValueError('Duplicate subjects')
    rows = frame.to_dict('records')
    for row in rows:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', row['subject_id']):
            raise ValueError('Invalid subject ID')
        if row['modality'] != 'T2' or row['modality_confirmed'].lower() not in ('true', '1'):
            raise ValueError('T2 modality must be explicitly confirmed')
        path = Path(row['image_path']).expanduser()
        row['image_path'] = path if path.is_absolute() else config['_path'].parent / path
    return rows


def workdir(config, sid):
    return config['output_dir'] / 't2_synthseg' / sid


def digest(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def commands(source, out):
    # SynthSeg reads the original MRI, not the skull-stripped derivative.
    return [
        ['mri_synthstrip', '-i', str(source), '-o', str(out/'brain.nii.gz'),
         '-m', str(out/'brain_mask.nii.gz'), '--fill', '0'],
        ['mri_synthseg', '--i', str(source), '--o', str(out/'segmentation.nii.gz'),
         '--resample', str(out/'resampled.nii.gz'), '--vol', str(out/'volumes.csv'),
         '--qc', str(out/'qc.csv'), '--robust', '--cpu', '--threads', '2']]


def validate_outputs(source, out):
    import nibabel as nib
    import numpy as np
    import pandas as pd
    from notebook_input import validate_image
    for name in ARTIFACTS:
        if not (out/name).is_file() or not (out/name).stat().st_size:
            raise ValueError('Missing output: ' + name)
    for name in ARTIFACTS[:4]:
        validate_image(out/name)
    original, brain, mask, labels, resampled = [nib.load(p) for p in (
        source, out/'brain.nii.gz', out/'brain_mask.nii.gz',
        out/'segmentation.nii.gz', out/'resampled.nii.gz')]
    for derived in (brain, mask):
        if derived.shape != original.shape or not np.allclose(derived.affine, original.affine):
            raise ValueError('SynthStrip changed source geometry')
    binary = np.asanyarray(mask.dataobj)
    if not np.isin(binary, (0, 1)).all() or not binary.any() or binary.all():
        raise ValueError('Invalid or degenerate brain mask')
    if not np.allclose(np.asanyarray(brain.dataobj), np.asanyarray(original.dataobj) * binary):
        raise ValueError('Skull-stripped image is inconsistent with mask')
    if labels.shape != resampled.shape or not np.allclose(labels.affine, resampled.affine):
        raise ValueError('Segmentation/resampled image geometry mismatch')
    values = np.asanyarray(labels.dataobj)
    if not np.equal(values, np.floor(values)).all() or values.min() < 0 or values.max() <= 0:
        raise ValueError('Invalid segmentation labels')
    for name in ('volumes.csv', 'qc.csv'):
        data = pd.read_csv(out/name)
        if len(data) != 1 or len(data.columns) < 2:
            raise ValueError('Expected a single-subject table: ' + name)
        numeric = data.iloc[:, 1:].apply(pd.to_numeric, errors='raise').to_numpy()
        if not np.isfinite(numeric).all() or (numeric < 0).any():
            raise ValueError('Invalid numerical output: ' + name)


def status(config):
    rows = []
    for row in cases(config):
        out = workdir(config, row['subject_id'])
        path = out/'status.json'
        info = json.loads(path.read_text()) if path.exists() else {'state': 'not_started'}
        complete = info['state'] == 'completed_pending_visual_qc'
        if complete:
            try:
                if digest(row['image_path']) != info['input_sha256']:
                    raise ValueError('Input changed since processing')
                for name in ARTIFACTS:
                    if digest(out/name) != info['output_sha256'][name]:
                        raise ValueError('Output changed: ' + name)
            except (OSError, KeyError, ValueError) as exc:
                complete = False
                info = dict(state='integrity_check_failed', error=str(exc))
        rows.append(dict(subject_id=row['subject_id'], complete=complete,
                         detail=info, output_dir=str(out)))
    return rows


def process(config):
    import fcntl
    import os
    from notebook_input import validate_image
    rows = cases(config)
    config['output_dir'].mkdir(parents=True, exist_ok=True)
    with (config['output_dir']/'t2.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for row in rows:
            if workdir(config, row['subject_id']).exists():
                raise FileExistsError('Existing T2 run; inspect it before retrying')
            validate_image(row['image_path'])
        for row in rows:
            out = workdir(config, row['subject_id'])
            out.mkdir(parents=True, exist_ok=False)
            source = row['image_path'].resolve()
            info = dict(state='running', pid=os.getpid(), modality='T2', module=MODULE,
                        input_path=str(source), input_sha256=digest(source),
                        commands=commands(source, out), qc_status='pending_visual_review',
                        normative_comparison=False, disease_prediction=None)
            (out/'status.json').write_text(json.dumps(info, indent=2))
            try:
                shell = '\n'.join(['set -eo pipefail', 'ml ' + MODULE,
                    'export OMP_NUM_THREADS=2 ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=2',
                    'command -v mri_synthstrip', 'command -v mri_synthseg',
                    'mri_synthstrip --version',
                    *[shlex.join(c) for c in info['commands']]])
                with (out/'processing.log').open('x') as log:
                    subprocess.run(['bash', '-lc', shell], stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
                validate_outputs(source, out)
                if digest(source) != info['input_sha256']:
                    raise ValueError('Input changed during processing')
                info.update(state='completed_pending_visual_qc',
                            output_sha256={name: digest(out/name) for name in ARTIFACTS})
            except Exception as exc:
                info.update(state='failed', error=str(exc))
                raise
            finally:
                (out/'status.json').write_text(json.dumps(info, indent=2))


def preview(path):
    import nibabel as nib
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    image = nib.as_closest_canonical(nib.load(path))
    data = image.get_fdata()
    positions = np.argwhere(data != 0)
    if not len(positions):
        raise ValueError('Empty brain image')
    center = np.median(positions, axis=0).astype(int)
    lo, hi = np.percentile(data[data != 0], (1, 99))
    fig = Figure(figsize=(9, 3))
    FigureCanvasAgg(fig)
    zooms = image.header.get_zooms()
    for ax, section, title, (h, v) in zip(fig.subplots(1, 3),
        (data[center[0], :, :], data[:, center[1], :], data[:, :, center[2]]),
        ('Sagittal: A right / S up', 'Coronal: R right / S up', 'Axial: R right / A up'),
        ((1, 2), (0, 2), (0, 1))):
        ax.imshow(section.T, origin='lower', cmap='gray', vmin=lo, vmax=hi, aspect=zooms[v]/zooms[h])
        ax.set_title(title, fontsize=8)
        ax.axis('off')
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format='png')
    return '<img style="max-width:100%" alt="T2 skull-stripped MRI" src="data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode() + '">'


def report(config):
    import pandas as pd
    checks = status(config)
    if not all(r['complete'] for r in checks):
        raise ValueError('T2 processing incomplete: ' + json.dumps(checks))
    paths = []
    for row in cases(config):
        sid = row['subject_id']
        out = workdir(config, sid)
        esc = html.escape
        body = ['<!doctype html><meta charset="utf-8"><h2>T2 research report: ' + esc(sid) + '</h2>',
            '<p>SynthStrip brain extraction and SynthSeg-robust regional volumes. Module: ' + MODULE + '.</p>',
            '<p><b>Processing complete; visual QC pending. Not a diagnosis.</b> '
            'No lesion segmentation, cortical thickness, Potvin ranges, or AD/Control classification is performed. '
            'SynthSeg outputs must not be treated as recon-all FS5.3 measurements.</p>',
            '<p>Age: ' + esc(row.get('age') or 'Unknown') + '; Sex: ' + esc(row.get('sex') or 'Unknown') + '</p>',
            preview(out/'brain.nii.gz'), '<h3>Descriptive regional volumes (mm3)</h3>',
            '<p>Soft-segmentation volumes as reported by SynthSeg; not normal reference ranges.</p>',
            pd.read_csv(out/'volumes.csv').T.to_html(header=False, escape=True),
            '<h3>Automated QC scores</h3><p>Scores do not replace visual review.</p>',
            pd.read_csv(out/'qc.csv').T.to_html(header=False, escape=True),
            '<p>Inspect segmentation.nii.gz over resampled.nii.gz for segmentation QC.</p>',
            '<p>Sources: <a href="https://surfer.nmr.mgh.harvard.edu/docs/synthstrip/">SynthStrip</a>; '
            '<a href="https://surfer.nmr.mgh.harvard.edu/fswiki/SynthSeg">SynthSeg</a>.</p>']
        path = out/'report.html'
        path.write_text(''.join(body))
        paths.append(path)
    return paths
