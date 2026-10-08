"""Back up and deploy interpretation rules, then regenerate all case reports."""
from datetime import datetime, timezone
import json
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import zipfile


def regenerate(root):
    from audit_all_patients import audit_all
    from audit_report_interpretation import audit
    folder = root / 'outputs/patient_audit_interpretation_20261003'
    audit_all(root, folder)
    audit(root, folder / 'patient_output_checks.json', folder)
    export_results(root, folder)


def export_results(root, folder):
    with zipfile.ZipFile(root / 'report_interpretation_results_20261003.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in folder.iterdir():
            if path.is_file():
                bundle.write(path, path.relative_to(root))
        for row in json.loads((folder / 'patient_output_checks.json').read_text()):
            if not row.get('report_path'):
                continue
            path = Path(row['report_path'])
            for suffix in ('_concise_report.html', '_interpretation.json', '_all_potvin_measurements.csv'):
                artifact = path.parent / (row['subject_id'] + suffix)
                bundle.write(artifact, artifact.relative_to(root))
        for name in ('interpretation_update_tests.log', 'interpretation_audit_tests.log'):
            if (root / name).exists():
                bundle.write(root / name, name)
        labels = root / 'workflow_sources/case_evaluation_expectations.json'
        if labels.exists():
            bundle.write(labels, labels.relative_to(root))
    print('REPORT_INTERPRETATION_RESULTS_READY', flush=True)


def install(root, archive):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = root / 'maintenance' / ('interpretation_update_backup_' + stamp)
    backup.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            relative = Path(name)
            if len(relative.parts) != 1 or relative.suffix != '.py':
                raise ValueError('Unexpected archive member: ' + name)
            target = root / relative
            if target.exists():
                shutil.copy2(target, backup / relative)
            target.write_bytes(bundle.read(name))
            py_compile.compile(str(target), doraise=True)
    with (root / 'interpretation_update_tests.log').open('w') as log:
        subprocess.run([sys.executable, '-m', 'unittest', 'test_report_interpretation', 'test_report_audit',
            'test_zheng_age_policy', 'test_pd_reviewed_comparison', 'test_meeting_workflow',
            'test_reference_focus', 'test_pd_evidence', 'test_case_controls', 'test_user_pipeline', '-v'],
            cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (root / 'interpretation_patient_audit.log').open('wb') as log:
        child = subprocess.Popen([sys.executable, str(root / 'install_interpretation_update.py'), '--audit'],
            cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    print('INTERPRETATION_UPDATE_TESTED_AUDIT_STARTED', child.pid, flush=True)


if __name__ == '__main__':
    root = Path(__file__).parent.resolve()
    if sys.argv[1] == '--audit':
        regenerate(root)
    else:
        install(root, sys.argv[1])
