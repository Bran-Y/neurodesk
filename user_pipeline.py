"""Portable research entry point. No dataset-specific covariate defaults."""
import argparse
import html
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import sys


def read_config(path):
    if not str(path).strip():
        raise ValueError('No configuration selected. Validate & use case first, or select an existing case config.json.')
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('Config must be an existing JSON file, not an image or folder: ' + str(path))
    config = json.loads(path.read_text())
    from reference_focus import focus
    config['reference_focus'] = focus(config)
    if config.get('modality', 'T1') not in ('T1', 'T2'):
        raise ValueError('Unsupported modality; no implicit T1 fallback')
    for key in ('subjects_dir', 'metadata_csv', 'output_dir'):
        p = Path(config[key]).expanduser()
        config[key] = p.resolve() if p.is_absolute() else (path.parent / p).resolve()
    config['_path'] = path
    return config


def participants(config):
    if config.get('modality', 'T1') != 'T1':
        raise ValueError('T2 cannot enter the T1 normative workflow')
    import pandas as pd
    frame = pd.read_csv(config['metadata_csv'], dtype={'subject_id': str})
    fields = ['subject_id', 'age', 'sex', 'scanner_field_strength', 'scanner_manufacturer']
    if frame.empty or not set(fields).issubset(frame.columns):
        raise ValueError('Provide at least one participant and columns: ' + ', '.join(fields))
    if frame.subject_id.duplicated().any():
        raise ValueError('Duplicate subject IDs')
    for row in frame.to_dict('records'):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', str(row['subject_id'])):
            raise ValueError('Invalid subject ID')
        for key in ('age', 'scanner_field_strength'):
            if not math.isfinite(float(row[key])) or float(row[key]) <= 0:
                raise ValueError('Missing/invalid ' + key + ': ' + row['subject_id'])
        if row['sex'] not in ('Male', 'Female') or row['scanner_manufacturer'] not in ('Siemens', 'GE', 'Philips'):
            raise ValueError('Normative model covariates missing/unsupported: ' + row['subject_id'])
    return frame


def completed(subject):
    required = ['scripts/recon-all.done', 'scripts/recon-all.log', 'scripts/build-stamp.txt',
                'mri/brain.mgz', 'stats/aseg.stats', 'stats/lh.aparc.stats', 'stats/rh.aparc.stats']
    missing = [p for p in required if not (subject/p).is_file()
               or (p != 'scripts/recon-all.done' and not (subject/p).stat().st_size)]
    if missing:
        return False, 'Missing: ' + ', '.join(missing)
    build = (subject/'scripts/build-stamp.txt').read_text().strip()
    if not re.search(r'(?<!\d)(?:v)?5\.3\.0(?!\d)', build):
        return False, 'Potvin entry requires verified FS5.3.0: ' + build
    if 'finished without error' not in (subject/'scripts/recon-all.log').read_text(errors='replace')[-4000:]:
        return False, 'Successful completion not confirmed in log'
    if list((subject/'scripts').glob('IsRunning*')):
        return False, 'IsRunning marker present; inspect process before use'
    return True, build


def status(config):
    if config.get('modality') == 'T2':
        from t2_pipeline import status as t2_status
        return t2_status(config)
    return [dict(subject_id=sid, complete=ok, detail=detail)
            for sid in participants(config).subject_id
            for ok, detail in [completed(config['subjects_dir']/sid)]]


def analyze(config, root=None, *, require_reviewed_qc=False):
    if config.get('modality') == 'T2':
        from t2_pipeline import report
        return report(config)
    import pandas as pd
    from neurodesk_literature_to_pgsql import parse_freesurfer_aseg_stats, parse_freesurfer_aparc_stats
    from finished_evidence_workflow import run_finished_workflow
    from concise_case_report import export_concise_report
    root = Path(root or Path(__file__).parent).resolve()
    checks = status(config)
    if not all(r['complete'] for r in checks):
        raise ValueError('Selected cohort not ready; no partial report generated: ' + json.dumps(checks))
    if require_reviewed_qc:
        from report_quality import read_qc
        reviews = {r['subject_id']: read_qc(dict(project_dir=root, fs_root=config['subjects_dir']),
                   r['subject_id'])['status'] for r in checks}
        if any(value != 'accepted' for value in reviews.values()):
            raise ValueError('Reviewed report requires accepted segmentation QC: ' + json.dumps(reviews))
    out = config['output_dir'] / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    frames = []
    for metadata in participants(config).to_dict('records'):
        sid = metadata['subject_id']
        subject = config['subjects_dir']/sid
        rows = parse_freesurfer_aseg_stats(subject/'stats/aseg.stats', sid, metadata=metadata)
        for side in ('lh', 'rh'):
            rows += parse_freesurfer_aparc_stats(subject/f'stats/{side}.aparc.stats', sid, hemisphere=side, metadata=metadata)
        frame = pd.DataFrame(rows)
        if frame.empty or frame.duplicated(['roi_name','hemisphere','imaging_metric']).any():
            raise ValueError('Empty or duplicated measurements: ' + sid)
        if not frame.value_numeric.map(lambda x: math.isfinite(float(x)) and float(x) >= 0).all():
            raise ValueError('Invalid measurement: ' + sid)
        if frame.imaging_metric.eq('cortical_thickness').sum() != 68:
            raise ValueError('Expected bilateral DK cortical coverage: ' + sid)
        # Override legacy parser defaults with the verified subject build stamp.
        frame['processing_software_version'] = '5.3.0'
        frame['atlas_version'] = '5.3.0'
        frame['processing_version_source'] = str(subject/'scripts/build-stamp.txt')
        for key in ('scanner_field_strength', 'scanner_manufacturer'):
            frame[key] = metadata[key]
        frame['scanner_source'] = str(config['metadata_csv'])
        frame['segmentation_qc_status'] = metadata.get('segmentation_qc_status', 'pending_visual_review')
        frames.append(frame)
    out.mkdir(parents=True)
    csv = out/'structural_features.csv'
    pd.concat(frames, ignore_index=True).to_csv(csv, index=False)
    # An empty private directory disables the legacy OASIS scanner inference.
    dataset = out/'no_dataset_defaults'
    dataset.mkdir()
    result = run_finished_workflow(root, csv, config['subjects_dir'], dataset,
                                   [r['subject_id'] for r in checks], out/'analysis',
                                   reference_focus=config.get('reference_focus', 'all'))
    for sid in result['run_manifest']['subject_ids']:
        export_concise_report(result, sid, out)
    (out/'input_configuration.json').write_text(json.dumps({k: str(v) if isinstance(v, Path) else v for k,v in config.items()}, indent=2))
    return result


def process(config):
    """Serial Neurodesk queue, protected against duplicate runners; never overwrites subjects."""
    if config.get('modality') == 'T2':
        from t2_pipeline import process as t2_process
        return t2_process(config)
    import fcntl
    import nibabel as nib
    frame = participants(config)
    root = config['subjects_dir']
    root.mkdir(parents=True, exist_ok=True)
    with (root/'user_pipeline.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inputs = []
        for row in frame.to_dict('records'):
            sid = row['subject_id']
            if (root/sid).exists():
                raise FileExistsError('Existing subject; refusing to restart/overwrite: ' + sid)
            if str(row.get('t1_confirmed','')).lower() not in ('true','1'):
                raise ValueError('User must confirm T1-weighted modality: ' + sid)
            path = Path(str(row.get('t1_path',''))).expanduser()
            path = path if path.is_absolute() else config['_path'].parent/path
            if not path.is_file() or not str(path).endswith(('.nii', '.nii.gz')):
                raise ValueError('Provide a NIfTI T1 file: ' + sid)
            image = nib.load(path)
            if len(image.shape) != 3 or any(n <= 1 for n in image.shape):
                raise ValueError('Expected a 3D structural image: ' + sid)
            inputs.append((sid, path.resolve()))
        for sid, path in inputs:
            command = 'ml freesurfer/5.3.0 && recon-all -sd ' + shlex.quote(str(root)) + ' -s ' + shlex.quote(sid) + ' -i ' + shlex.quote(str(path)) + ' -all'
            print('START', sid, flush=True)
            with (root/(sid+'.processing.log')).open('x') as log:
                subprocess.run(['bash','-lc',command], stdout=log, stderr=subprocess.STDOUT, check=True)
            ok, reason = completed(root/sid)
            if not ok:
                raise RuntimeError(reason)
            print('DONE', sid, flush=True)


def launch(config):
    config['output_dir'].mkdir(parents=True, exist_ok=True)
    path = config['output_dir']/('queue_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.log')
    with path.open('x') as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(config['_path']), '--process'],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return dict(pid=child.pid, log=str(path), note='Submitted, not completed. Refresh status and inspect logs.')


def workflow_summary_html(root):
    """The notebook's saved-report entry is the single report navigation block."""
    return ''


def show():
    global _close_active_ui
    previous = globals().get('_close_active_ui')
    if previous is not None:
        previous()
    import ipywidgets as w
    from IPython.display import display, clear_output
    path = w.Text(value='config.json', description='Config:')
    reference = w.Dropdown(description='References:', options=[
        ('Use saved configuration', 'config'),
        ('PD + Potvin (no AD comparison)', 'PD'),
        ('All available references', 'all')])
    check = w.Button(description='Check status')
    run = w.Button(description='Generate reports')
    submit = w.Button(description='Start processing')
    consent = w.Checkbox(value=False, description='I confirm the selected modality and authorise processing')
    output = w.Output()
    panel = None
    active = True
    from notebook_input import input_form
    def changed():
        if panel is not None:
            panel.close()
        path.value = ''
        consent.value = False
        output.clear_output()
    form = input_form(Path(__file__).parent, lambda value: setattr(path, 'value', value), changed)
    def act(action):
        nonlocal panel
        if not active:
            return
        if panel is not None:
            panel.close()
            panel = None
        with output:
            clear_output(wait=False)
            try:
                config = read_config(path.value)
                if reference.value != 'config':
                    from reference_focus import save_focus
                    save_focus(config, reference.value)
                if action == 'status':
                    print(json.dumps(status(config), indent=2))
                elif action == 'process':
                    if not consent.value:
                        raise ValueError('Explicit processing confirmation required')
                    print(launch(config))
                else:
                    if config.get('modality') == 'T2':
                        from IPython.display import HTML
                        for report_path in analyze(config):
                            display(HTML(report_path.read_text()))
                            print('Saved report:', report_path)
                        return {'ok': True}
                    from report_quality import PreReportQC
                    checks = status(config)
                    if not all(row['complete'] for row in checks):
                        raise ValueError('Processing incomplete: ' + json.dumps(checks))
                    def generate(reviewed):
                        nonlocal panel
                        with output:
                            try:
                                result = analyze(config, require_reviewed_qc=reviewed)
                                if panel is not None:
                                    panel.close()
                                clear_output(wait=False)
                                from compact_report_panel import ReportPanel
                                panel = ReportPanel(result)
                                panel.show()
                            except Exception as error:
                                print(type(error).__name__ + ': ' + str(error))
                    panel = PreReportQC(config, Path(__file__).parent, generate)
                    panel.show()
                return {'ok': True}
            except Exception as error:
                print(type(error).__name__ + ': ' + str(error))
                return {'ok': False, 'error': type(error).__name__ + ': ' + str(error)}
    check.on_click(lambda _: act('status'))
    run.on_click(lambda _: act('report'))
    submit.on_click(lambda _: act('process'))
    def invalidate(change=None):
        nonlocal panel
        if panel is not None:
            panel.close()
            panel = None
        consent.value = False
        output.clear_output()
    reference.observe(invalidate, names='value')
    path.observe(invalidate, names='value')
    from case_controls import CaseControls
    def request(config_path, reference_value, authorised, action):
        if not active:
            return {'ok': False, 'error': 'This interface is inactive. Rerun the entry cell.'}
        path.value = config_path
        reference.value = reference_value
        consent.value = authorised
        return act(action)
    controls = CaseControls(request, Path(__file__).parent)
    def sync_config(change):
        controls.config = change['new']
    path.observe(sync_config, names='value')
    output.add_class('case-switch-results')
    box = w.VBox([form, w.HTML('<h4>Run / existing configuration</h4>'), controls, output])
    box.add_class('case-switch-workflow')
    def close():
        nonlocal active
        if not active:
            return
        active = False
        invalidate()
        path.unobserve(invalidate, names='value')
        path.unobserve(sync_config, names='value')
        reference.unobserve(invalidate, names='value')
        for button in (check, submit, run):
            button.disabled = True
        box.close()
        controls.close()
    _close_active_ui = close
    display(box)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    parser.add_argument('--process', action='store_true')
    args = parser.parse_args()
    c = read_config(args.config)
    process(c) if args.process else print(json.dumps(status(c), indent=2))
