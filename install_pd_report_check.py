"""Install the PD significance clarification and regenerate only the three PD reports."""
from datetime import datetime, timezone
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import zipfile


def install(root, archive):
    backup = root / 'maintenance' / ('pd_report_check_backup_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if name not in ('pd_evidence.py', 'test_pd_evidence.py', 'audit_pd_reports.py', 'install_pd_report_check.py'):
                raise ValueError('Unexpected package member')
            target = root / name
            if target.exists():
                shutil.copy2(target, backup / name)
            target.write_bytes(bundle.read(name))
            py_compile.compile(str(target), doraise=True)
    with (root / 'pd_report_check_tests.log').open('w') as log:
        subprocess.run([sys.executable, '-m', 'unittest', 'test_pd_evidence', 'test_pd_supplement',
            'test_pd_reviewed_comparison', 'test_reference_focus', 'test_report_interpretation',
            'test_report_audit', 'test_meeting_workflow', 'test_user_pipeline', '-v'],
            cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (root / 'pd_report_check.log').open('wb') as log:
        child = subprocess.Popen([sys.executable, str(root / 'audit_pd_reports.py')],
            cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    print('PD_REPORT_FIX_TESTED_CHECK_STARTED', child.pid, flush=True)


if __name__ == '__main__':
    install(Path(__file__).parent.resolve(), sys.argv[1])
