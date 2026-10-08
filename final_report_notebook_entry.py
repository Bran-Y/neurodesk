"""Show the clean saved-report entry without stale widget review summaries."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil


def update(root):
    root = Path(root)
    path = root / '00_START_HERE.ipynb'
    notebook = json.loads(path.read_text())
    entries = [cell for cell in notebook['cells'] if cell.get('cell_type') == 'code'
               and 'user_pipeline.show()' in ''.join(cell.get('source', []))]
    if len(entries) != 1 or 'from importlib import reload' not in ''.join(entries[0]['source']):
        raise ValueError('Notebook entry changed; preserve it for inspection')
    if not (root / 'outputs/final_reports_20261004/FINAL_REPORTS.html').is_file():
        raise ValueError('Final report index missing')
    backup = root / 'maintenance' / ('final_notebook_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.ipynb')
    shutil.copy2(path, backup)
    entries[0]['outputs'] = []
    entries[0]['execution_count'] = None
    source = ['### Patient reports\n',
        '[Open final patient reports](outputs/final_reports_20261004/FINAL_REPORTS.html)\n',
        '\n', 'Saved research results are available without running the cells below. '
        'Incomplete segmentation QC and excluded source-conflicting directions remain indicated. '
        'Run the workflow cell below only to use the live controls.\n']
    markers = [cell for cell in notebook['cells'] if cell.get('metadata', {}).get('final_reports_entry')]
    if markers:
        if len(markers) != 1:
            raise ValueError('Duplicate final report entries')
        markers[0]['source'] = source
    else:
        notebook['cells'].insert(1, dict(cell_type='markdown', id='final-reports-entry',
            metadata=dict(final_reports_entry=True), source=source))
    path.write_text(json.dumps(notebook, indent=1))
    print('CLEAN NOTEBOOK ENTRY READY', flush=True)


if __name__ == '__main__':
    update(Path(__file__).parent)
