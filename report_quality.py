"""Coverage accounting, source-bound manual QC, and kernel-independent report links."""
import hashlib
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd

QC_FILES = ('mri/orig.mgz', 'mri/brainmask.mgz', 'mri/brain.mgz', 'mri/aseg.mgz', 'stats/aseg.stats',
            'stats/lh.aparc.stats', 'stats/rh.aparc.stats',
            'surf/lh.white', 'surf/rh.white', 'surf/lh.pial', 'surf/rh.pial')
QC_CHECKS = ('skull_stripping', 'cortical_boundaries', 'subcortical_labels', 'motion_artifacts')


def source_fingerprint(fs_root, subject_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', subject_id):
        raise ValueError('Invalid subject ID')
    root = Path(fs_root).resolve() / subject_id
    digest, missing = hashlib.sha256(), []
    digest.update(str(root).encode())
    for name in QC_FILES:
        path = root / name
        digest.update(name.encode())
        if not path.is_file():
            missing.append(name)
            digest.update(b'MISSING')
            continue
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest(), missing


def qc_directory(result, subject_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', subject_id):
        raise ValueError('Invalid subject ID')
    key = hashlib.sha256(str(Path(result.get('fs_root', '.')).resolve()).encode()).hexdigest()[:16]
    return Path(result.get('project_dir', '.')) / 'outputs' / 'segmentation_qc' / key / subject_id


def read_qc(result, subject_id):
    directory = qc_directory(result, subject_id)
    paths = sorted(directory.glob('*.json')) if directory.exists() else []
    if not paths:
        return {'status': 'pending_visual_review'}
    try:
        record = json.loads(paths[-1].read_text())
        fingerprint, missing = source_fingerprint(result['fs_root'], subject_id)
        if (record['subject_id'] != subject_id or record['source_fingerprint'] != fingerprint or
                (missing and record['status'] == 'accepted')):
            return {'status': 'stale_review', 'note': 'Source files changed or are incomplete; review again.'}
        if record['status'] not in ('accepted', 'rejected') or not record['reviewer'].strip():
            raise ValueError('Invalid review record')
        if record['status'] == 'accepted' and not all(record['checks'].get(k) is True for k in QC_CHECKS):
            raise ValueError('Incomplete accepted review')
        return record
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'status': 'invalid_review', 'note': 'QC record could not be verified.'}


def save_qc(result, subject_id, reviewer, note, checks, decision, *, expected_fingerprint):
    if decision not in ('accepted', 'rejected') or not reviewer.strip() or not note.strip():
        raise ValueError('A reviewer, dated note and acceptance/rejection decision are required')
    fingerprint, missing = source_fingerprint(result['fs_root'], subject_id)
    if fingerprint != expected_fingerprint:
        raise ValueError('Source files changed while reviewing. Reload the case before recording QC.')
    if decision == 'accepted' and (missing or not all(checks.get(k) is True for k in QC_CHECKS)):
        raise ValueError('Acceptance requires all source files and all four visual checks')
    now = datetime.now(timezone.utc)
    record = dict(subject_id=subject_id, status=decision, reviewer=reviewer.strip(),
                  note=note.strip(), checks={k: checks.get(k) is True for k in QC_CHECKS},
                  reviewed_at=now.isoformat(), source_fingerprint=fingerprint, missing_files=missing)
    directory = qc_directory(result, subject_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (now.strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(record, stream, indent=2)
    return record


def qc_html(result, subject_id, compact=False):
    from assistant_visual_review import preview_html
    record = read_qc(result, subject_id)
    details = ' | '.join(str(record[k]) for k in ('reviewer', 'reviewed_at', 'note') if k in record)
    if compact:
        from assistant_visual_review import detailed_record
        sampled = detailed_record(result, subject_id)
        outcome = sampled.get('final_outcome', '') if sampled and sampled.get('status') != 'stale_assistant_review' else ''
        return ('<h4>Segmentation QC</h4><p><b>' + html.escape(record['status']) + '</b>' +
                (': ' + html.escape(str(record['note']))
                 if record['status'] != 'accepted' and record.get('note') else '') + '</p>' +
                ('<p>Sampled-image QC (assistant): ' + html.escape(outcome) +
                 ' Full-volume manual confirmation remains incomplete.</p>'
                 if outcome and record['status'] != 'accepted' else ''))
    return ('<h4>Segmentation quality review</h4><p><b>' + html.escape(record['status']) +
            '</b>: ' + html.escape(details) + '</p><p>Processing completion and source approval '
            'do not establish segmentation quality. The skull-stripped preview alone is not '
            'a cortical/subcortical boundary inspection. Pending, stale or rejected QC limits interpretation.</p>' +
            preview_html(result, subject_id))


def coverage_html(result, subject_id):
    case = result['normative'].loc[result['normative'].subject_id.eq(subject_id)]
    calculated = case.calculation_status.eq('calculated')
    within = calculated & case.range_status.eq('within_95pi')
    outside = calculated & case.range_status.isin(['below_95pi', 'above_95pi'])
    invalid = calculated & ~(within | outside)
    gaps = case.loc[~calculated]
    reasons = gaps.get('exclusion_reason', pd.Series(index=gaps.index, dtype=object))
    counts = reasons.fillna('Reason not recorded').replace('', 'Reason not recorded').value_counts()
    out = [f'<h4>Coverage | {html.escape(subject_id)}</h4><p>{len(case)} measurements = '
           f'{int(within.sum())} within + {int(outside.sum())} outside + {len(gaps)} not calculated'
           f' + {int(invalid.sum())} invalid classifications. Unit: ROI x hemisphere x metric. '
           'This is not a count of independent disease indicators.</p>',
           counts.rename_axis('Reason').reset_index(name='Measurements').to_html(index=False, escape=True)]
    if invalid.any():
        out.append('<p><b>Classification integrity error: calculated rows have unknown status.</b></p>')
    from pd_evidence import compare_result
    pd_rows = pd.DataFrame(compare_result(result, subject_id))
    if not pd_rows.empty:
        unmatched = pd_rows.loc[pd_rows.match_status.ne('matched_for_context')]
        cols = [c for c in ('source_structure', 'hemisphere', 'metric', 'context') if c in unmatched]
        out.append(f'<p>PD references: {len(pd_rows) - len(unmatched)}/{len(pd_rows)} matched for '
                   'group-effect context. Unmatched references are not evidence against PD.</p>')
        out.append(unmatched[cols].to_html(index=False, escape=True))
    return ''.join(out)


def source_contributions(papers, comparisons):
    """Expose the separate PD reference store without inflating registry counts."""
    papers = papers.copy()
    papers['connected_group_effect_records'] = 0
    papers['matched_group_effect_features'] = 0
    selected = papers.doi.eq('10.1002/mds.28706')
    if not comparisons.empty:
        key = ['evidence_id'] if 'evidence_id' in comparisons else ['source_structure', 'hemisphere', 'metric']
        references = comparisons.drop_duplicates(key)
        papers.loc[selected, 'connected_group_effect_records'] = len(references)
        papers.loc[selected, 'matched_group_effect_features'] = int(references.match_status.eq('matched_for_context').sum())
        papers.loc[selected & papers.unique_evidence_rows.eq(0), 'zero_evidence_reason'] = (
            'General registry has no extracted rows; separate PD group-effect reference store is connected (see counts).')
    return papers


def saved_report_link(path, subject_id, kind='numeric/MRI'):
    path = Path(path).resolve()
    prefix = os.environ.get('JUPYTERHUB_SERVICE_PREFIX', '')
    server_root = Path(os.environ.get('JUPYTER_SERVER_ROOT', str(Path.home()))).resolve()
    label = 'Saved ' + kind + ' report for ' + subject_id
    try:
        relative = path.relative_to(server_root)
    except ValueError:
        relative = None
    if prefix.startswith('/') and relative is not None:
        location = '<a target="_blank" rel="noopener" href="' + html.escape(
            prefix.rstrip('/') + '/files/' + quote(relative.as_posix(), safe='/'), quote=True) + '">' + html.escape(label) + '</a>'
    else:
        location = html.escape(label + ': ' + str(path))
    return '<p>' + location + '. Saved snapshot, not live; no running kernel required. Server/login must remain available.</p>'


def export_ai_snapshot(result, subject_id, payload, response):
    from ai_evidence_assistant import render_explanation, payload_hash
    if not re.fullmatch(r'[A-Za-z0-9_-]+', subject_id):
        raise ValueError('Invalid subject ID')
    directory = Path(result['output_dir']) / 'concise_reports'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (subject_id + '_ai_report.html')
    content = ('<!doctype html><html><head><meta charset="utf-8"><title>AI research snapshot</title>'
               '<style>body{font:16px Georgia,serif;max-width:1000px;margin:32px auto;padding:16px}'
               'td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}</style></head><body>'
               '<h2>' + html.escape(subject_id) + '</h2><p>Saved research snapshot: ' +
               datetime.now(timezone.utc).isoformat() + ' | Scope: ' +
               html.escape(str(payload.get('reference_focus', 'not recorded'))) + '</p><p>Evidence SHA256: ' +
               payload_hash(payload) + '</p>' + render_explanation(response, payload) + '</body></html>')
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    return path


class QCPanel:
    def __init__(self, result, subject_widget, on_saved):
        import ipywidgets as w
        self.result, self.subject, self.on_saved = result, subject_widget, on_saved
        self.reviewer = w.Text(description='Reviewer:')
        self.note = w.Textarea(description='QC note:')
        self.checks = {k: w.Checkbox(value=False, description=k.replace('_', ' ')) for k in QC_CHECKS}
        self.decision = w.Dropdown(description='Decision:', options=[('Select...', None), ('Accept', 'accepted'), ('Reject', 'rejected')])
        self.save = w.Button(description='Record manual QC')
        self.status = w.HTML()
        self.save.on_click(self.record)
        self.box = w.Accordion(children=[w.VBox([w.HTML('<p>Record only checks you actually performed '
            'with segmentation/surface overlays. Nothing is automatically approved.</p>'), self.status,
            self.reviewer, self.note, *self.checks.values(), self.decision, self.save])],
            titles=('Manual segmentation QC',), selected_index=None)
        self.subject.observe(self.reset, names='value')
        self.closed = False
        self.reset()

    def reset(self, change=None):
        self.sid = self.subject.value
        self.fingerprint, _ = source_fingerprint(self.result['fs_root'], self.sid)
        self.note.value = self.reviewer.value = ''
        self.decision.value = None
        for box in self.checks.values():
            box.value = False
        self.status.value = qc_html(self.result, self.sid)

    def record(self, _=None):
        if self.closed or self.sid != self.subject.value:
            return
        try:
            save_qc(self.result, self.sid, self.reviewer.value, self.note.value,
                    {k: w.value for k, w in self.checks.items()}, self.decision.value,
                    expected_fingerprint=self.fingerprint)
            self.status.value = qc_html(self.result, self.sid)
            self.on_saved()
        except (ValueError, OSError) as exc:
            self.status.value = '<p>' + html.escape(str(exc)) + '</p>'

    def close(self):
        self.closed = True
        self.subject.unobserve(self.reset, names='value')
        self.save.on_click(self.record, remove=True)
        self.save.disabled = True
        self.box.close()


class PreReportQC:
    """Review the selected subject before generating the numeric report."""
    def __init__(self, config, root, on_generate):
        import ipywidgets as w
        from user_pipeline import participants
        from segmentation_viewer import SegmentationViewer
        self.closed = False
        self.on_generate = on_generate
        self.result = dict(fs_root=config['subjects_dir'], project_dir=Path(root))
        self.subject = w.Dropdown(description='QC subject:', options=list(participants(config).subject_id))
        self.viewer = SegmentationViewer(self.result)
        self.qc = QCPanel(self.result, self.subject, self.refresh)
        self.qc.box.selected_index = 0
        self.reviewed = w.Button(description='Generate QC-confirmed report', button_style='primary',
                                 layout=w.Layout(width='260px'))
        self.draft = w.Button(description='Generate final research report', layout=w.Layout(width='260px'))
        self.reviewed.on_click(self.generate_reviewed)
        self.draft.on_click(self.generate_draft)
        self.state = w.HTML()
        self.box = w.VBox([w.HTML('<h3>Segmentation QC before report generation</h3>'),
            self.subject, self.viewer.box, self.qc.box, self.state, w.HBox([self.reviewed, self.draft])])
        self.subject.observe(self.switch, names='value')
        self.switch()

    def refresh(self):
        statuses = {sid: read_qc(self.result, sid)['status'] for sid in self.subject.options}
        self.reviewed.disabled = any(status != 'accepted' for status in statuses.values())
        self.draft.disabled = any(status == 'rejected' for status in statuses.values())
        self.state.value = ('<p>' + html.escape(' | '.join(sid + ': ' + status for sid, status in statuses.items())) +
            '</p><p>Final research reports retain the current segmentation QC status. '
            'QC-confirmed reports require accepted QC for every selected subject.</p>')

    def switch(self, change=None):
        if self.closed:
            return
        self.viewer.show(self.subject.value)
        self.refresh()

    def generate_reviewed(self, _=None):
        self.refresh()
        if not self.closed and not self.reviewed.disabled:
            self.on_generate(True)

    def generate_draft(self, _=None):
        self.refresh()
        if not self.closed and not self.draft.disabled:
            self.on_generate(False)

    def show(self):
        from IPython.display import display
        display(self.box)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.subject.unobserve(self.switch, names='value')
        self.reviewed.on_click(self.generate_reviewed, remove=True)
        self.draft.on_click(self.generate_draft, remove=True)
        self.viewer.close()
        self.qc.close()
        self.box.close()
