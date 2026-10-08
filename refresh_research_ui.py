"""Refresh presentation in the existing kernel without resetting human QC inputs."""
from importlib import import_module, reload
import json
from pathlib import Path
import shutil


OLD_INTRO = ('Record your review before generating a reviewed report; a labelled '
             'research draft is available while QC is incomplete.')
NEW_INTRO = ('Final research reports retain the current segmentation QC status. '
             'QC-confirmed reports require accepted segmentation QC.')


def update_notebook(root):
    path = root / '00_START_HERE.ipynb'
    notebook = json.loads(path.read_text())
    changed = False
    for cell in notebook['cells']:
        if cell.get('cell_type') != 'markdown':
            continue
        source = ''.join(cell.get('source', []))
        if OLD_INTRO in source:
            cell['source'] = source.replace(OLD_INTRO, NEW_INTRO).splitlines(keepends=True)
            changed = True
    if changed:
        backup = root / 'maintenance/research_release_notebook_before_intro_20261005.ipynb'
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(json.dumps(notebook, indent=1))


def refresh(root):
    import ipywidgets as w
    from IPython.display import display
    from report_quality import PreReportQC as previous_qc

    widgets = list(w.Widget.widgets.values())
    inputs = [item for item in widgets if isinstance(item, (
        w.Text, w.Textarea, w.Checkbox, w.Dropdown, w.IntSlider, w.FloatSlider))]
    before = [(item, item.value) for item in inputs]
    workflows = [item for item in widgets
                 if isinstance(item, w.VBox) and 'case-switch-workflow' in item._dom_classes]
    if len(workflows) != 1:
        raise ValueError('Expected exactly one existing live workflow; refusing to reset QC inputs')

    for name in ('research_report_release', 'evidence_readiness', 'literature_audit',
                 'assistant_visual_review', 'report_interpretation', 'pd_reviewed_comparison',
                 'pd_evidence', 'workflow_audit', 'report_quality', 'concise_case_report',
                 'compact_report_panel', 'user_pipeline'):
        reload(import_module(name))
    from report_quality import PreReportQC
    # Existing bound callbacks keep the original function object.
    previous_qc.refresh.__code__ = PreReportQC.refresh.__code__
    labels = {'Generate reviewed report': 'Generate QC-confirmed report',
              'Generate research draft': 'Generate final research report'}
    old_state = ('A research draft can be generated while review is incomplete. '
                 'Reviewed reports require accepted QC for every selected subject.')
    new_state = ('Final research reports retain the current segmentation QC status. '
                 'QC-confirmed reports require accepted QC for every selected subject.')
    changed = 0
    for item in widgets:
        if isinstance(item, w.Button) and item.description in labels:
            item.description = labels[item.description]
            item.layout.width = '260px'
            changed += 1
        elif isinstance(item, w.HTML) and old_state in item.value:
            item.value = item.value.replace(old_state, new_state)
            changed += 1
    if any(item.value != value for item, value in before):
        raise AssertionError('A live form value changed during presentation refresh')
    display(workflows[0])
    print(f'Presentation refreshed: {changed} labels; {len(inputs)} live inputs preserved. '
          'No QC decision submitted.')


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    update_notebook(root)
    try:
        get_ipython
    except NameError:
        print('Notebook introduction updated. Run this helper in the existing notebook kernel for live labels.')
    else:
        refresh(root)
