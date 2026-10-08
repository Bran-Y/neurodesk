"""Guarded presentation release; preserve numerical exports and source/QC history."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys

EXPECTED = {
    'concise_case_report.py': 'fdbde439b9ab4c4d268af23ad217f92be0d5d80ce5a1648dac721508e9fe5c1c',
    'report_quality.py': '4eab731c8d13e3423bb0ad29c5e4da365e48c477a5937bb7b50a8a422c6a0c4d',
    'build_final_reports.py': '48cf3f84f808ac16c5694fe2a28932f24091cc5e7751b6f955e982ec982d931b',
    'compact_report_panel.py': '7a520537f0accf50317acad58e1dcf3c7f84a46926c74824a825661c36b18848',
    'evidence_readiness.py': 'db42b5a308848aa11702778d6671c70eecdc5a0b3ad339c74244e8f97b9fa887',
    'pd_evidence.py': '8cccde9c2e46911f5cd37415118c8019980ca00a47f8338a2e66bcca4f5a94a2',
    'literature_audit.py': '6c87d7b9dbcce6d866331cf81e677b8ee0169f4b1d272e83a2a50dbf11d463c9',
    'test_reference_focus.py': '7e17a0b6c1dfb7c45959903834ef4d924c6fa018cf9d6857a08e8bc9e3e5b39f',
}
NEW = ['research_report_release.py', 'test_research_report_release.py', 'install_research_release.py']
PREVIOUS_RELEASE = {
    'research_report_release.py': 'abc335d0aa661d4c2472b2756373787a06797689a7665dc7820413a197d9b564',
    'install_research_release.py': '44b2d460a71b16b44ad6d2cd4f1e3c391557c8669c87195285c8df5269f68dda',
}
TESTS = ['test_research_report_release', 'test_report_presentation', 'test_barnes_2005_statistics',
         'test_source_resolution', 'test_report_interpretation', 'test_report_audit',
         'test_pd_evidence', 'test_pd_reviewed_comparison', 'test_reference_focus',
         'test_user_pipeline', 'test_meeting_workflow', 'test_segmentation_holds',
         'test_zero_paper_review', 'test_evidence_readiness']


def hashes(root, folders):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in folders for p in (root / folder).rglob('*') if p.is_file()}


def install(root):
    source = Path(__file__).resolve().parent
    root = Path(root).resolve()
    for name in [*EXPECTED, *NEW]:
        incoming, existing = source / name, root / name
        if not incoming.is_file():
            raise FileNotFoundError(incoming)
        if existing.exists() and incoming.read_bytes() != existing.read_bytes():
            if hashlib.sha256(existing.read_bytes()).hexdigest() not in (
                    EXPECTED.get(name), PREVIOUS_RELEASE.get(name)):
                raise ValueError('Concurrent source change; not overwriting: ' + name)
    notebook = root / '00_START_HERE.ipynb'
    nb = json.loads(notebook.read_text())
    entries = [c for c in nb['cells'] if c.get('cell_type') == 'code'
               and 'user_pipeline.show()' in ''.join(c.get('source', []))]
    if len(entries) != 1 or 'from importlib import reload' not in ''.join(entries[0]['source']):
        raise ValueError('Notebook entry changed; inspect before release')
    protected = hashes(root, ['workflow_sources', 'outputs/segmentation_qc'])
    backup = root / 'maintenance' / ('research_release_backup_' +
                                    datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    for name in [*EXPECTED, *NEW, '00_START_HERE.ipynb',
                 'outputs/final_reports_20261004/FINAL_REPORTS.html',
                 'outputs/final_reports_20261004/verification.json']:
        current = root / name
        if current.is_file():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current, saved)
    (backup / 'protected_sources.json').write_text(json.dumps(protected, indent=2))
    for name in [*EXPECTED, *NEW]:
        shutil.copy2(source / name, root / name)
        py_compile.compile(str(root / name), doraise=True)
    with (backup / 'tests.log').open('w') as log:
        subprocess.run([sys.executable, '-m', 'unittest', *TESTS, '-v'], cwd=root,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    print('REGRESSION TESTS PASSED', backup, flush=True)
    sys.path.insert(0, str(root))
    from build_final_reports import build
    build(root)
    if protected != hashes(root, ['workflow_sources', 'outputs/segmentation_qc']):
        raise ValueError('Source evidence or human QC changed')
    # Reload presentation helpers before the existing entry reload loop.
    entry = entries[0]
    source_text = ''.join(entry['source'])
    extra = ('import research_report_release, evidence_readiness, literature_audit\n'
             'for release_module in (research_report_release, evidence_readiness, literature_audit):\n'
             '    reload(release_module)\n')
    if extra not in source_text:
        source_text = source_text.replace('from importlib import reload\n',
                                          'from importlib import reload\n' + extra, 1)
    entry['source'] = source_text.splitlines(keepends=True)
    entry['outputs'], entry['execution_count'] = [], None
    notebook.write_text(json.dumps(nb, indent=1))
    print('FINAL RELEASE VERIFIED: source/QC history unchanged; notebook entry refreshed', flush=True)


if __name__ == '__main__':
    install(sys.argv[1])
