"""Completed value checks are separate from interpretation permission and patient QC."""
import hashlib
import html
import json
from pathlib import Path

ENIGMA_ID = 'PD-ENIGMA-2021:Subvol:LLatVent:HY4-5'
HANGANU_ID = 'HANGANU_Q0013'
MANIFEST = 'workflow_sources/paper_reading_reviews/source_value_verifications.json'


def verify(root):
    root = Path(root)
    manifest = root / MANIFEST
    if not manifest.exists():
        return []
    records = json.loads(manifest.read_text())['records']
    by_id = {r['evidence_id']: r for r in records}
    if len(records) != 2 or set(by_id) != {ENIGMA_ID, HANGANU_ID}:
        raise ValueError('Unexpected source-value verification inventory')
    for row in records:
        if (row['verification_status'] != 'completed' or row['direction_authorized'] is not False
                or row['patient_qc_changed'] is not False):
            raise ValueError('Value verification cannot grant interpretation or patient QC')
        for item in [dict(path=row['source_pdf'], sha256=row['source_pdf_sha256']),
                     *row['screenshots']]:
            path = root / 'workflow_sources' / item['path']
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('Verified source changed or is missing: ' + item['path'])
    enigma = by_id[ENIGMA_ID]
    if enigma['values'] != dict(summary_d=-.357, detailed_d=.357, b=2761.46, percent_difference=18.43):
        raise ValueError('ENIGMA verified values changed')
    stage = json.loads((root / 'workflow_sources/Disease/PD/enigma_pd_stage_statistics.json').read_text())
    row = next(r for r in stage['records'] if r['evidence_id'] == ENIGMA_ID)
    if (row['effect_size'] != .357 or row['regression_coefficient'] != 2761.46
            or row['percent_difference'] != 18.43 or row['direction_eligible'] is not False):
        raise ValueError('ENIGMA source values or direction guard changed')
    hanganu = by_id[HANGANU_ID]
    if hanganu['values'] != dict(mean_change_mm3=-43.67, percent_change=1.4):
        raise ValueError('Hanganu verified values changed')
    sources = json.loads((root / 'workflow_sources/Disease/PD/reviewed_pd_quantitative_tables.json').read_text())
    row = next(r for s in sources['sources'] if s['doi'] == hanganu['doi']
               for r in s['records'] if r['evidence_id'] == HANGANU_ID)
    if (row['structure'] != 'Pallidum' or row['group'] != 'PD-MCI'
            or row['record_kind'] != 'longitudinal_change' or row['mean'] != -43.67
            or row['percent_change'] != 1.4):
        raise ValueError('Hanganu source values or longitudinal definition changed')
    return records


def render(root):
    rows = verify(root)
    if not rows:
        return ''
    escape = html.escape
    body = ['<details><summary>Verified source values and use restrictions (2 items)</summary>',
            '<table><thead><tr><th>Source / location</th><th>Source-value check</th>'
            '<th>Reported values</th><th>Permitted use</th></tr></thead><tbody>']
    for row in rows:
        body.append('<tr>' + ''.join('<td>' + escape(str(value)) + '</td>' for value in (
            row['source'] + ' | ' + row['source_locations'], 'Completed',
            row['reported_values'], row['permitted_use'])) + '</tr>')
    body.append('</tbody></table></details>')
    return ''.join(body)
