"""Deploy presentation-only audit after verifying the existing panel version."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

EXPECTED_PANEL = 'a12e2f4778fdda62439fe490c9de92cf881e34764c9854b4f3eae44fadc421fe'
PREVIOUS_DEPLOYMENT = {'compact_report_panel.py':'d2ef8b8bc5b04222eea7d46b45a5ebc127d590de99c9b8d8568884921654485b',
                       'zero_paper_review.py':'6d577958f7b1acdace8ded2f8a95123f4c307b0bcec03f58e0318598eef872a9',
                       'test_zero_paper_review.py':'e311b8369c98b0f31dbdb728689215db2cb92faf95af10bbb2453ae0d3023017'}
FILES = ['zero_paper_review.py', 'test_zero_paper_review.py', 'compact_report_panel.py']


def install(destination):
    source = Path(__file__).resolve().parent
    root = Path(destination).resolve()
    for name in FILES:
        incoming, current = source / name, root / name
        if not incoming.is_file():
            raise FileNotFoundError(incoming)
        if current.exists() and current.read_bytes() != incoming.read_bytes():
            digest = hashlib.sha256(current.read_bytes()).hexdigest()
            if digest != PREVIOUS_DEPLOYMENT.get(name) and not (name == 'compact_report_panel.py' and digest == EXPECTED_PANEL):
                raise ValueError('Refusing to overwrite diverged file: ' + name)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = root / 'maintenance' / ('zero_paper_review_backup_' + stamp)
    backup.mkdir(parents=True)
    # No patient report, feature export, evidence table or approval/QC file may change.
    protected = [p for base in ('outputs', 'workflow_sources', 'cases') for p in (root / base).rglob('*')
                 if p.is_file() and p.suffix in ('.csv', '.json', '.html')
                 and 'literature_zero_review_20261004' not in p.parts]
    before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    for name in FILES:
        current = root / name
        if current.exists():
            shutil.copy2(current, backup / name)
        shutil.copy2(source / name, current)
    sys.path.insert(0, str(root))
    from zero_paper_review import publish
    baseline = root / 'maintenance/zero_paper_baseline.json'
    if not baseline.is_file():
        raise FileNotFoundError('Patient source-coverage baseline required')
    publish(root, baseline)
    after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    if before != after:
        raise ValueError('Protected patient/source files changed')
    (backup / 'protected_file_verification.json').write_text(json.dumps(dict(
        checked_files=len(before), unchanged=True, sha256=before), indent=2))
    print('PROTECTED FILES UNCHANGED', len(before), flush=True)
    print('BACKUP', backup, flush=True)


if __name__ == '__main__':
    install(sys.argv[1])
