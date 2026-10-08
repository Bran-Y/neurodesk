"""Source-level regional findings; never convert surface clusters into patient diagnoses."""
import hashlib
import html
import json
from pathlib import Path

MANIFEST = 'workflow_sources/paper_reading_reviews/hanganu_2014_figure_review.json'
DOI = '10.1093/brain/awu036'
RECORD_IDS = {
    'HANGANU-F1-MCI-NONMCI', 'HANGANU-F1-MCI-HC', 'HANGANU-F1-NONMCI-HC',
    'HANGANU-F2-ALLPD-POSITIVE', 'HANGANU-F2-ALLPD-NEGATIVE', 'HANGANU-F2-MCI-NEGATIVE',
}


def verify(root):
    root = Path(root)
    path = root / MANIFEST
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if (data['doi'] != DOI or data['verification_status'] != 'completed'
            or data['patient_qc_changed'] is not False or data['patient_numeric_use'] is not False):
        raise ValueError('Figure review cannot authorize patient numeric interpretation or QC')
    source = root / 'workflow_sources' / data['source_pdf']
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != data['source_pdf_sha256']:
        raise ValueError('Hanganu primary source changed or is missing')
    rows = data['records']
    if len(rows) != 6 or {r['record_id'] for r in rows} != RECORD_IDS:
        raise ValueError('Unexpected Hanganu regional review inventory')
    for row in rows:
        if any(row[field] is not None for field in ('exact_p', 'exact_r', 'corrected_significant_per_roi')):
            raise ValueError('Exact ROI statistics not supplied by the reviewed source')
        if row['figure'] == 'Figure 2' and 'uncorrected' not in row['statistical_status']:
            raise ValueError('Figure 2 correlations must retain uncorrected status')
    figures = {r['figure']: r for r in data['figures']}
    if len(data['figures']) != 2 or set(figures) != {'Figure 1', 'Figure 2'}:
        raise ValueError('Unexpected figure inventory')
    for figure in figures.values():
        if (figure['display_p_threshold'] != .05 or figure['display_threshold_is_corrected_status'] is not False
                or any(figure[field] is not None for field in
                       ('exact_corrected_p_values', 'cluster_coordinates', 'cluster_extents'))):
            raise ValueError('Display threshold is not per-cluster corrected significance')
    if figures['Figure 2']['reported_statistical_status'] != 'p<0.001 uncorrected correlations':
        raise ValueError('Figure 2 threshold changed')
    expected = [('PD-MCI vs HC', 'A', 'right'), ('PD-MCI vs HC', 'B', 'right')]
    if [(r['comparison'], r['panel'], r['hemisphere']) for r in figures['Figure 1']['visible_asterisks']] != expected:
        raise ValueError('Reviewed figure-level marker locations changed')
    return data


def render(root):
    data = verify(root)
    if data is None:
        return ''
    escape = html.escape
    body = ['<details><summary>Hanganu 2014: verified regional findings (6 summaries)</summary>',
            '<p>Longitudinal literature context only, not a single-scan diagnosis. '
            'Figure 1 mixes FDR p&lt;0.05 asterisk-marked clusters with p&lt;0.001 uncorrected clusters. '
            'Figure 2 reports p&lt;0.001 uncorrected correlations. Both display maps at p&lt;0.05; '
            'that display threshold is not corrected significance.</p>',
            '<div style="overflow:auto"><table><thead><tr>',
            '<th>Figure / comparison</th><th>Direction</th><th>Regions / laterality</th>',
            '<th>Statistical status</th><th>Source</th></tr></thead><tbody>']
    for row in data['records']:
        values = (row['figure'] + ' | ' + row['comparison_or_group'], row['direction'],
                  row['regions'] + ' | ' + row['laterality'], row['statistical_status'], row['source_location'])
        body.append('<tr>' + ''.join('<td>' + escape(value) + '</td>' for value in values) + '</tr>')
    body.append('</tbody></table></div><p>Not reported by the source: exact corrected p values, '
                'cluster coordinates/extents and explicit starred-cluster-to-named-ROI assignments. '
                'No whole-ROI corrected-significance labels or patient QC approvals were inferred.</p></details>')
    return ''.join(body)
