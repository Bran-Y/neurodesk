"""Install the extraction/count correction without overwriting diverged modules."""
import hashlib
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone

EXPECTED = {
    'literature_audit.py': '83113048bba7bb1e17eeaa23ae77dcdb8242329215bc78bd8dd6485c185e93f7',
    'workflow_audit.py': 'da59a5b1a70cfb0be1a97b65165be435b47bb7521bbc09e1d89eaad0dd37eed6',
    'compact_report_panel.py': '015d130ab14eb20ff4ba19eecf31d0e302fda645e0291c7c4366f7980f2af115',
    'concise_case_report.py': 'f006ba2f515841408e987580875b0c4244b0bd1fa184d53af19f73191d6c78dd',
}
FILES = list(EXPECTED) + [
    'workflow_sources/paper_reading_reviews/barnes_2005_reported_statistics.json',
    'test_barnes_2005_statistics.py',
]


def install(destination):
    source = Path(__file__).resolve().parent
    destination = Path(destination).resolve()
    for name in FILES:
        incoming, current = source / name, destination / name
        if not incoming.is_file():
            raise FileNotFoundError(incoming)
        if current.exists():
            digest = hashlib.sha256(current.read_bytes()).hexdigest()
            identical = current.read_bytes() == incoming.read_bytes()
            if not identical and digest != EXPECTED.get(name):
                raise ValueError('Refusing to overwrite diverged file: ' + name)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = destination / 'maintenance' / ('barnes_statistics_backup_' + stamp)
    for name in FILES:
        current = destination / name
        if current.exists():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current, saved)
        current.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, current)
    print('Installed six abstract-derived statistics and explicit applicability counts.')
    print('Original modules preserved in', backup)


if __name__ == '__main__':
    install(sys.argv[1])
