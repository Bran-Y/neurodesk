"""Install presentation-only changes after guarding current remote sources."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import zipfile

FILES = {'report_quality.py', 'concise_case_report.py', 'pd_reviewed_comparison.py',
         'user_pipeline.py', 'test_report_presentation.py', 'build_final_reports.py',
         'install_final_presentation.py'}


def install(root, package):
    with zipfile.ZipFile(package) as bundle:
        if set(bundle.namelist()) != FILES | {'expected_sources.json'}:
            raise ValueError('Unexpected package files')
        expected = json.loads(bundle.read('expected_sources.json'))
        for name, digest in expected.items():
            if name not in FILES or hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Source changed: ' + name)
        backup = root / 'maintenance' / ('final_presentation_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        backup.mkdir(parents=True)
        for name in FILES:
            path = root / name
            if path.exists():
                shutil.copy2(path, backup / name)
            path.write_bytes(bundle.read(name))
            py_compile.compile(str(path), doraise=True)
    with (backup / 'tests.log').open('w') as log:
        subprocess.run([sys.executable, '-m', 'unittest', 'test_report_presentation',
            'test_report_interpretation', 'test_report_audit', 'test_pd_evidence',
            'test_pd_reviewed_comparison', 'test_reference_focus', 'test_user_pipeline', '-v'],
            cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    print('TESTS PASSED', backup, flush=True)
    from build_final_reports import build
    build(root)


if __name__ == '__main__':
    install(Path(__file__).parent.resolve(), sys.argv[1])
