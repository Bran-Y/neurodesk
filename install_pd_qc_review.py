"""Install source-bound assistant QC notes, leaving manual QC and MRI sources untouched."""
from datetime import datetime, timezone
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import zipfile

MEMBERS = {'assistant_visual_review.py', 'test_assistant_visual_review.py',
           'finalize_pd_qc_review.py', 'install_pd_qc_review.py'}


def install(root, archive):
    backup = root / 'maintenance' / ('pd_qc_review_backup_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        if set(bundle.namelist()) != MEMBERS:
            raise ValueError('Unexpected QC review package members')
        for name in bundle.namelist():
            target = root / name
            if target.is_file():
                shutil.copy2(target, backup / name)
            target.write_bytes(bundle.read(name))
            py_compile.compile(str(target), doraise=True)
    with (root / 'pd_qc_review_tests.log').open('w') as stream:
        subprocess.run([sys.executable, '-m', 'unittest', 'test_assistant_visual_review',
            'test_pd_evidence', 'test_pd_supplement', 'test_pd_reviewed_comparison',
            'test_reference_focus', 'test_report_interpretation', 'test_report_audit',
            'test_meeting_workflow', 'test_user_pipeline', '-v'], cwd=root,
            stdout=stream, stderr=subprocess.STDOUT, check=True)
    with (root / 'pd_qc_review.log').open('w') as stream:
        child = subprocess.Popen([sys.executable, str(root / 'finalize_pd_qc_review.py')],
            cwd=root, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    print('QC_REVIEW_TESTED_REFRESH_STARTED', child.pid, flush=True)


if __name__ == '__main__':
    install(Path(__file__).parent.resolve(), sys.argv[1])
