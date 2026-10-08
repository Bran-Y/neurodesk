"""Apply the schema-only correction against the exact original QC deployment."""
from pathlib import Path
import subprocess
import sys
import zipfile


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    with zipfile.ZipFile(root / 'segmentation_holds_20261004.zip') as original, zipfile.ZipFile(root / 'segmentation_holds_schema_20261004.zip') as schema, zipfile.ZipFile(root / 'segmentation_holds_final_20261004.zip') as previous, zipfile.ZipFile(sys.argv[1]) as update:
        names = ('segmentation_holds.py', 'test_segmentation_holds.py', 'install_segmentation_holds.py', 'finished_evidence_workflow.py')
        payload = {name: update.read(name) for name in names}
        for name in names:
            allowed = [original.read(name), payload[name]]
            if name in schema.namelist():
                allowed.append(schema.read(name))
            if name in previous.namelist():
                allowed.append(previous.read(name))
            if (root / name).read_bytes() not in allowed:
                raise ValueError('Module changed independently: ' + name)
        for name in names:
            (root / name).write_bytes(payload[name])
    subprocess.run([sys.executable, '-m', 'unittest', 'test_segmentation_holds',
        'test_pd_evidence', 'test_pd_supplement', 'test_pd_reviewed_comparison',
        'test_assistant_visual_review', 'test_report_presentation', 'test_report_interpretation',
        'test_meeting_workflow', 'test_user_pipeline', 'test_reference_focus'], cwd=root, check=True)
    from install_segmentation_holds import refresh
    refresh(root)
