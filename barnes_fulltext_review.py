"""Verified source summaries, separate from patient-reference and human-QC stores."""
import hashlib
import html
import json
from pathlib import Path

DOI = '10.1159/000084560'
MANIFEST = 'workflow_sources/paper_reading_reviews/barnes_2005_fulltext_review.json'


def verify(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    path = root / MANIFEST
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if (data['doi'] != DOI or data['verification_status'] != 'completed'
            or any(data[key] is not False for key in
                   ('patient_numeric_use', 'patient_qc_changed', 'human_signatures_changed'))
            or data['standard_deviation'] is not None
            or data['individual_prediction_interval'] is not None
            or data['confidence_level'] != .95 or data['baseline_statistic_kind'] != 'geometric_mean'):
        raise ValueError('Full-text check must not authorize patient interpretation or human QC')
    source = root / data['source_pdf']
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != data['source_pdf_sha256']:
        raise ValueError('Barnes reviewed primary PDF changed or is missing')
    rows = data['records']
    if len(rows) != 16 or len({(r['group'], r['visit'], r['metric'], r['side']) for r in rows}) != 16:
        raise ValueError('Unexpected Barnes Table 2 inventory')
    if any(r['n'] != {'Control': 50, 'AD': 32}[r['group']]
           or not r['ci_lower'] < r['value'] < r['ci_upper']
           or (r['metric'] != 'atrophy' and r['statistic_kind'] != 'geometric_mean') for r in rows):
        raise ValueError('Table 2 cohort, interval or mean kind changed')
    old = json.loads((root / 'workflow_sources/paper_reading_reviews/barnes_2005_reported_statistics.json').read_text())
    from research_report_release import verify_barnes
    verify_barnes(old)
    by_id = {r['record_id']: r for r in old}
    overlap = [r for r in rows if r['existing_record_id']]
    if (len(overlap) != 4 or len({r['existing_record_id'] for r in overlap}) != 4
            or data['new_context_statistics'] != 12 or data['overlapping_existing_statistics'] != 4):
        raise ValueError('Do not count four repeated abstract atrophy estimates as new evidence')
    for row in overlap:
        original = by_id[row['existing_record_id']]
        if (row['value'], row['ci_lower'], row['ci_upper'], row['n']) != (
                original['reported_value'], original['confidence_interval_lower'],
                original['confidence_interval_upper'], original['cohort_sample_size']):
            raise ValueError('Abstract and Table 2 atrophy values disagree')
    return data


def render(root=None):
    data = verify(root)
    if data is None:
        return ''
    escape = html.escape
    body = ['<details><summary>Barnes 2005: verified full-text Table 2</summary>',
            '<p>' + escape(data['permitted_use']) + '</p>',
            '<p><b>Definition:</b> ' + escape(data['ratio_definition'] + '. ' + data['ratio_location']) +
            '</p><p><b>Measurement:</b> ' + escape(data['measurement_method'] + '. ' + data['anatomical_definition']) +
            '</p><p>' + escape(data['counting_policy']) + '</p>',
            '<div style="overflow:auto"><table><thead><tr>',
            '<th>Group / n</th><th>Visit</th><th>Metric / side</th><th>Mean / unit</th>',
            '<th>95% CI of mean</th><th>Statistic kind</th></tr></thead><tbody>']
    for row in data['records']:
        cells = (f"{row['group']} / {row['n']}", row['visit'], row['metric'] + ' / ' + row['side'],
                 f"{row['value']:g} {row['unit']}", f"{row['ci_lower']:g} to {row['ci_upper']:g}", row['statistic_kind'])
        body.append('<tr>' + ''.join('<td>' + escape(cell) + '</td>' for cell in cells) + '</tr>')
    body.append('</tbody></table></div><p><b>Source:</b> ' + escape(data['table_location']) + '</p>')
    for key in ('printed_summary_note', 'annualization', 'statistical_caution', 'conclusion'):
        body.append('<p>' + escape(data[key]) + '</p>')
    body.append('</details>')
    return ''.join(body)
