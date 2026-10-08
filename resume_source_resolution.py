"""Resume after correcting the obsolete presentation fixture, with a hash guard."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    if str(root) != '/home/jovyan/neurodesk/neurodesk_user_workflow_20260916T063153Z':
        raise ValueError('Unexpected destination')
    path = root / 'test_meeting_workflow.py'
    with zipfile.ZipFile(sys.argv[1]) as archive:
        updated = archive.read('test_meeting_workflow.py')
    if hashlib.sha256(path.read_bytes()).hexdigest() not in (
            '1c0d79c52d427c8381e5075018a982fafebfd48fc9585e7f7aaf7326e39c1ae8',
            hashlib.sha256(updated).hexdigest()):
        raise ValueError('Test file changed; not overwriting')
    backup = root / 'outputs/source_resolution_20261004/originals/test_meeting_workflow.py'
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_bytes(updated)
    subprocess.run([sys.executable, '-m', 'unittest', 'test_source_resolution',
        'test_pd_supplement', 'test_pd_evidence', 'test_report_interpretation',
        'test_report_presentation', 'test_meeting_workflow', 'test_user_pipeline',
        'test_assistant_visual_review'], cwd=root, check=True)
    subprocess.run([sys.executable, 'finalize_sampled_qc.py'], cwd=root, check=True)
    subprocess.run([sys.executable, 'build_final_reports.py', '--source-refresh'], cwd=root, check=True)
    print('SOURCE AND QC REPORT UPDATE COMPLETE', flush=True)
