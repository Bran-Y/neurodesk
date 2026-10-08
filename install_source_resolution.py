"""Guarded deployment into the existing authenticated Neurodesk workspace."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

EXPECTED = {
    'report_quality.py': '25d70806aedcdecb98c79bafde36ecf1c33bd66a7cc9b2fa82157cea47f74e9d',
    'build_final_reports.py': '8e2da42ec6702ccfebafbebf60b8ecc536007c2a7a40b6ccf22ad91c40838790',
    'import_pd_supplement.py': '2fa3fe409d929f913b0491220e926a3efda4f3b10db1c0c459068fa3a014e7b8',
    'test_pd_supplement.py': 'fd08ebe602b99f29b41cbc3487b324570b0f1e5df1ce443d6b344f8e9a28d1fc',
    'workflow_sources/Disease/PD/enigma_pd_group_statistics.json': 'f745cd5c0920a92c7584dd2f94bdd91587559f5b6bb4c02b3309b6b36029f926',
    'workflow_sources/Disease/PD/enigma_pd_stage_statistics.json': '352b8a239393fc4a0bc6513931d8e52316ed509aa4161dca0de081ea41a935f5',
}
FILES = ['report_quality.py', 'build_final_reports.py', 'import_pd_supplement.py',
         'test_pd_supplement.py', 'resolve_enigma_sources.py', 'source_resolution_exports.py',
         'finalize_sampled_qc.py', 'test_source_resolution.py']


def install(package):
    root = Path(__file__).resolve().parent
    if str(root) != '/home/jovyan/neurodesk/neurodesk_user_workflow_20260916T063153Z':
        raise ValueError('Unexpected deployment destination')
    with zipfile.ZipFile(package) as archive:
        payload = {name: archive.read(name) for name in FILES}
    for name, expected in EXPECTED.items():
        path = root / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        replacement = hashlib.sha256(payload[name]).hexdigest() if name in payload else None
        if actual not in (expected, replacement):
            raise ValueError('Existing file changed; stopped without overwriting: ' + name)
    for name in set(FILES) - EXPECTED.keys():
        path = root / name
        if path.exists() and path.read_bytes() != payload[name]:
            raise ValueError('Unexpected existing new module: ' + name)
    backup = root / 'outputs/source_resolution_20261004/originals'
    for name in EXPECTED:
        target = backup / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, target)
    for name, data in payload.items():
        (root / name).write_bytes(data)
    subprocess.run([sys.executable, 'resolve_enigma_sources.py'], cwd=root, check=True)
    subprocess.run([sys.executable, '-m', 'unittest', 'test_source_resolution',
        'test_pd_supplement', 'test_pd_evidence', 'test_report_interpretation',
        'test_report_presentation', 'test_meeting_workflow', 'test_user_pipeline',
        'test_assistant_visual_review'], cwd=root, check=True)
    subprocess.run([sys.executable, 'finalize_sampled_qc.py'], cwd=root, check=True)
    subprocess.run([sys.executable, 'build_final_reports.py', '--source-refresh'], cwd=root, check=True)
    print('SOURCE AND QC REPORT UPDATE COMPLETE', flush=True)


if __name__ == '__main__':
    install(sys.argv[1])
