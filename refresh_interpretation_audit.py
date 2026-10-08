"""Refresh audit checks and the notebook link without rerunning MRI analysis."""
from datetime import datetime, timezone
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import zipfile


def install(root, archive):
    sys.path.insert(0, str(root.resolve()))
    names = {'user_pipeline.py', 'audit_report_interpretation.py', 'test_report_audit.py',
             'install_interpretation_update.py', 'refresh_interpretation_audit.py',
             'workflow_sources/case_evaluation_expectations.json'}
    backup = root / 'maintenance' / ('interpretation_audit_backup_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        if set(bundle.namelist()) != names:
            raise ValueError('Unexpected audit update contents')
        for name in names:
            target = root / name
            if target.exists():
                (backup / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup / name)
            target.write_bytes(bundle.read(name))
            if target.suffix == '.py':
                py_compile.compile(str(target), doraise=True)
    with (root / 'interpretation_audit_tests.log').open('w') as log:
        subprocess.run([sys.executable, '-m', 'unittest', 'test_report_audit', 'test_user_pipeline', '-v'],
            cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    from audit_report_interpretation import audit
    from install_interpretation_update import export_results
    folder = root / 'outputs/patient_audit_interpretation_20261003'
    audit(root, folder / 'patient_output_checks.json', folder)
    export_results(root, folder)


if __name__ == '__main__':
    install(Path(__file__).parent.resolve(), sys.argv[1])
