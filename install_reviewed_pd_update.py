"""Deploy audited source/table changes; do not touch keys or live notebook cells."""
from datetime import datetime, timezone
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import zipfile


def install(root, archive):
    root = Path(root).resolve()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = root / 'maintenance' / ('reviewed_pd_update_backup_' + stamp)
    backup.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts or name.endswith('/'):
                raise ValueError('Unexpected archive path: ' + name)
            target = root / relative
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(name))
            if target.suffix == '.py':
                py_compile.compile(str(target), doraise=True)
    with (root / 'reviewed_pd_update_tests.log').open('w') as log:
        subprocess.run([sys.executable, '-m', 'unittest', 'test_pd_reviewed_comparison',
            'test_meeting_workflow', 'test_reference_focus', 'test_pd_evidence',
            'test_case_controls', 'test_user_pipeline', '-v'], cwd=root,
            stdout=log, stderr=subprocess.STDOUT, check=True)
    with (root / 'reviewed_pd_patient_audit.log').open('wb') as log:
        child = subprocess.Popen([sys.executable, str(root / 'audit_all_patients.py'),
            '--root', str(root), '--output-dir', str(root / 'outputs/patient_audit_reviewed_pd_20261003')],
            cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    print('DEPLOYED_TESTED_AUDIT_STARTED', child.pid, flush=True)


if __name__ == '__main__':
    install(Path(__file__).parent, sys.argv[1])
