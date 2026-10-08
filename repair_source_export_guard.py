"""Include the derived atlas-context export in the bounded source refresh check."""
from pathlib import Path
import subprocess
import sys
import zipfile


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    if str(root) != '/home/jovyan/neurodesk/neurodesk_user_workflow_20260916T063153Z':
        raise ValueError('Unexpected destination')
    names = ['source_resolution_exports.py', 'test_source_resolution.py']
    with zipfile.ZipFile(sys.argv[1]) as updated, zipfile.ZipFile(root / 'source_resolution_20261004.zip') as baseline:
        payload = {name: updated.read(name) for name in names}
        with zipfile.ZipFile(root / 'fix_source_guard_20261004.zip') as previous_fix:
            previous = {name: previous_fix.read(name) for name in names}
        for name in names:
            if (root / name).read_bytes() not in (baseline.read(name), previous[name], payload[name]):
                raise ValueError('File changed; stopped: ' + name)
        for name in names:
            (root / name).write_bytes(payload[name])
    subprocess.run([sys.executable, '-m', 'unittest', 'test_source_resolution',
        'test_pd_supplement', 'test_pd_evidence', 'test_report_interpretation',
        'test_report_presentation', 'test_meeting_workflow', 'test_user_pipeline',
        'test_assistant_visual_review'], cwd=root, check=True)
    subprocess.run([sys.executable, 'build_final_reports.py', '--source-refresh'], cwd=root, check=True)
    print('SOURCE AND QC REPORT UPDATE COMPLETE', flush=True)
