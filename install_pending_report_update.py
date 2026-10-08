"""Deploy only reviewed files with stale-source guards and recoverable backups."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import zipfile

FILES = {'assistant_visual_review.py', 'report_quality.py', 'report_interpretation.py',
         'pd_evidence.py', 'pd_reviewed_comparison.py', 'concise_case_report.py', 'user_pipeline.py',
         'review_pending_reports.py', 'review_enigma_source.py', 'test_report_presentation.py', 'notebook_entry_reviewed.py',
         'install_pending_report_update.py'}
TESTS = ['test_report_presentation', 'test_assistant_visual_review', 'test_report_interpretation',
         'test_report_audit', 'test_pd_evidence', 'test_pd_reviewed_comparison', 'test_meeting_workflow',
         'test_reference_focus', 'test_case_controls', 'test_user_pipeline']


def install(root, archive):
    with zipfile.ZipFile(archive) as bundle:
        if set(bundle.namelist()) != FILES | {'expected_sources.json'}:
            raise ValueError('Unexpected deployment contents')
        expected = json.loads(bundle.read('expected_sources.json'))
        for name, sha in expected.items():
            if name not in FILES or hashlib.sha256((root / name).read_bytes()).hexdigest() != sha:
                raise ValueError('Remote source changed: ' + name)
        notebook_path = root / '00_START_HERE.ipynb'
        notebook = json.loads(notebook_path.read_text())
        entries = [cell for cell in notebook['cells'] if cell.get('cell_type') == 'code'
                   and 'user_pipeline.show()' in ''.join(cell.get('source', []))]
        if len(entries) != 1 or 'for module in (pd_evidence, workflow_audit,' not in ''.join(entries[0]['source']):
            raise ValueError('Notebook entry differs; preserve and inspect it before updating')
        backup = root / 'maintenance' / ('pending_report_backup_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        backup.mkdir(parents=True)
        shutil.copy2(notebook_path, backup / notebook_path.name)
        for name in FILES:
            target = root / name
            if target.exists():
                shutil.copy2(target, backup / name)
            target.write_bytes(bundle.read(name))
            py_compile.compile(str(target), doraise=True)
        entries[0]['source'] = bundle.read('notebook_entry_reviewed.py').decode().splitlines(keepends=True)
        notebook_path.write_text(json.dumps(notebook, indent=1))
    print('BACKUP', backup, flush=True)
    with (root / 'pending_report_tests_20261004.log').open('w') as log:
        subprocess.run([sys.executable, '-m', 'unittest', *TESTS, '-v'], cwd=root,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    print('TESTS PASSED', flush=True)
    from review_pending_reports import run
    run(root)


if __name__ == '__main__':
    install(Path(__file__).parent.resolve(), sys.argv[1])
