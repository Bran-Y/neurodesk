"""Source-bound observations from images actually viewed, not human QC approval."""
import hashlib
import base64
import html
import json
from pathlib import Path


def detailed_record(result, subject_id):
    """Validate both the source data and the images that were actually inspected."""
    root = Path(result.get('project_dir', '.'))
    record = None
    for relative in ('outputs/pending_review_20261004/review_observations.json',
                     'outputs/pd_qc_detailed_20261003/review_observations.json'):
        path = root / relative
        if path.is_file():
            records = json.loads(path.read_text()).get('subjects', [])
            record = next((item for item in records if item['subject_id'] == subject_id), None)
            if record is not None:
                break
    if record is None:
        return None
    from report_quality import source_fingerprint
    fingerprint, missing = source_fingerprint(result['fs_root'], subject_id)
    if missing or fingerprint != record['source_fingerprint']:
        return {'status': 'stale_assistant_review'}
    for item in record['images']:
        relative = Path(item['relative_path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid evidence image path')
        image = root / relative
        if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != item['sha256']:
            return {'status': 'stale_assistant_review'}
    if record.get('reviewer_role') != 'assistant' or record.get('human_qc_accepted') is not False:
        raise ValueError('Assistant observations must not claim human acceptance')
    return record


def detailed_html(result, record):
    if record['status'] == 'stale_assistant_review':
        return '<p><b>Assistant QC observations are stale; inspect the current source files again.</b></p>'
    cell_style = ' style="white-space:normal;overflow-wrap:anywhere;padding:8px;vertical-align:top"'
    rows = ''.join('<tr>' + ''.join('<td' + cell_style + '>' + html.escape(item[key]) + '</td>'
                   for key in ('check', 'assessment', 'observation', 'action')) + '</tr>' for item in record['checks'])
    out = ['<div style="white-space:normal;overflow-wrap:anywhere;min-width:0;width:100%">',
           '<h4>Assistant detailed segmentation inspection (not human sign-off)</h4>',
           '<p><b>' + html.escape(record['status']) + '</b> | ' + html.escape(record['reviewed_at']) +
           '</p><p>' + html.escape(record['scope']) + '</p>',
           '<table width="100%" style="width:100%;table-layout:fixed"><tr><th>Check</th><th>Assessment</th>'
           '<th>Observation</th><th>Next action</th></tr>' + rows + '</table>',
           '<p>' + html.escape(record['summary']) + '</p>',
           '<details><summary>Open inspected original/overlay pairs and slice evidence</summary>']
    root = Path(result.get('project_dir', '.'))
    for item in record['images']:
        out.append('<h5>' + html.escape(item['relative_path'].split('/')[-1]) + '</h5>')
        out.append('<img style="max-width:100%" src="data:image/png;base64,' +
                   base64.b64encode((root / item['relative_path']).read_bytes()).decode() + '">')
    out.append('</details><p>Human reviewer name, decision and checklist remain separate. '
               'This inspection does not assign a disease or authorize reviewed-report status.</p></div>')
    return ''.join(out)


def preview_html(result, subject_id):
    record = detailed_record(result, subject_id)
    if record is not None:
        return detailed_html(result, record)
    root = Path(result.get('project_dir', '.'))
    path = root / 'outputs/assistant_visual_review_20261003/observations.json'
    if not path.exists():
        return ''
    records = json.loads(path.read_text()).get('subjects', [])
    record = next((item for item in records if item['subject_id'] == subject_id), None)
    if record is None:
        return ''
    for item in record.get('images', []):
        relative = Path(item['relative_path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid evidence image path')
        image = root / relative
        if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != item['sha256']:
            return '<p>Assistant image observations are stale or unavailable; inspect current overlays.</p>'
    notes = ''.join('<li>' + html.escape(note) + '</li>' for note in record['observations'])
    return ('<h4>Assistant sampled image observations (not human sign-off)</h4><p>' +
            html.escape(record['status']) + '</p><ul>' + notes + '</ul><p>' +
            html.escape(record['scope']) + '</p>')
