"""Source-bound longitudinal statistics; never a single-scan patient reference."""
import hashlib
import html
import json
from pathlib import Path

DOI = '10.1016/j.neurobiolaging.2007.02.011'
TITLE = 'Increased hippocampal atrophy rates in AD over 6 months using serial MR imaging'
FOLDER = 'workflow_sources/paper_reading_reviews/'
SOURCE = FOLDER + 'barnes_2008_reported_statistics.json'
MANIFEST = FOLDER + 'barnes_2008_fulltext_review.json'
PDF = FOLDER + 'raw/barnes_2008_S0197458007000504.pdf'
PDF_SHA = 'a9be06639d772b30e62aa8f00ef3e4f7674db1505c9524eb130530d402f4d8d1'
SCOPE = ('Verified Table 2 annualized hippocampal atrophy rates (%/year), not single-scan '
         'volumes. Serial MRI and matching manual MIDAS segmentation/annualization are '
         'required; MIDAS-to-FreeSurfer equivalence is not established. Context only; '
         'not individual diagnostic evidence.')
# Table 2 is ordered left, right, total; each pair is 12 months then 6 months.
TABLE = [('lh',12,.02,1.25,4.50,3.29,'<'), ('lh',6,.26,2.39,4.12,4.22,'='),
         ('rh',12,.52,1.37,4.68,3.23,'<'), ('rh',6,.54,2.45,3.81,3.16,'='),
         ('total_left_plus_right',12,.28,.93,4.57,2.98,'<'),
         ('total_left_plus_right',6,.41,1.69,3.95,3.01,'<')]


def records():
    rows = []
    for side, months, hc, hc_sd, ad, ad_sd, relation in TABLE:
        for group, mean, sd, n in [('Control',hc,hc_sd,20), ('AD',ad,ad_sd,36)]:
            rows.append(dict(record_id=f'BARNES2008-{group}-{side}-{months}M',
                paper_code='DIS-009', source_title=TITLE, doi=DOI, year=2008,
                source_url='https://doi.org/' + DOI,
                source_location='Table 2, journal p.1201 (PDF page 3); n from Table 1 p.1200',
                source_check_status='primary_fulltext_statistics_verified_context_only',
                extraction_method='Text extraction cross-checked against rendered primary PDF Table 2, table note and Methods',
                extraction_status='fulltext_table2_verified', human_review_status='not_assigned_by_assistant',
                roi_name='hippocampus', hemisphere=side,
                imaging_metric='annualized_hippocampal_volume_atrophy_rate', diagnosis=group,
                cohort_sample_size=n, reported_value=mean, standard_deviation=sd,
                unit='%/year', statistic_kind='arithmetic_mean_and_standard_deviation',
                interval_months=months, measurement_method='Manual MIDAS hippocampal segmentation by one operator',
                p_value=.0001, p_value_relation=relation,
                p_value_comparison='AD versus Control; shared between the two group estimates',
                comparison_id=f'BARNES2008-ADvsControl-{side}-{months}M',
                confidence_interval_lower=None, confidence_interval_upper=None,
                numeric_use=False, patient_numeric_use=False, comparison_compatible=False,
                applicability_note=SCOPE))
    return rows


def manifest():
    return dict(doi=DOI, source_pdf=PDF, source_pdf_sha256=PDF_SHA,
        verification_status='completed', table_location='Table 2 p.1201; Table 1 and Methods p.1200; Discussion/Conclusions pp.1201-1202',
        statistic_records=12, group_comparisons=6, independent_cohorts=1,
        patient_numeric_use=False, patient_qc_changed=False, human_signatures_changed=False,
        permitted_use=SCOPE,
        total_definition='Atrophy calculated from total left plus right hippocampal volume; do not add or average left/right percentage rates.',
        annualization='Log-transformed volumes assuming constant proportionate hippocampal loss (Methods 2.3). Both 6-month and 12-month estimates are already annualized; do not multiply the 6-month table values by two.',
        annualization_equation=None, days_per_year_convention=None,
        six_month_scan_pair_aggregation=None,
        anatomical_definition='Dentate gyrus, hippocampus proper, subiculum and alveus. Coronal posterior-to-anterior manual segmentation; minimum threshold 70% of mean brain intensity.',
        registration='Triplets registered to MNI305 with 6 DOF; repeat scans to baseline with 9 DOF to correct voxel-size changes. Not a validated FreeSurfer normative adjustment.',
        cohort=dict(AD=36, Control=20, scanner='1.5T GE Signa', visits_months=[0,6,12]),
        mean_interscan_days=dict(AD_6=179,Control_6=181,AD_12=365,Control_12=364),
        interval_comparison_p=dict(AD_total_mean=.18,Control_total_mean=.69,
                                   Control_variance=.007,AD_variance=.98),
        mean_ci=None, individual_diagnostic_threshold=None,
        source_text_discrepancy=('Discussion p.1201 says 6-month mean rates were lower in both groups; '
            'Table 2 controls are higher at 6 months (total 0.41 versus 0.28 at 12 months). '
            'Retain Table 2 exactly; do not adopt or repair that directional prose.'),
        conclusion='Group-level consistency across intervals does not establish individual agreement or diagnosis; the authors report overlap between AD and controls.',
        counting_policy='Twelve group mean/SD estimates share six AD-versus-control comparisons from one cohort. Do not count estimates or intervals as independent disease votes.')


def verify(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    if not (root / MANIFEST).exists():
        return None
    data = json.loads((root / MANIFEST).read_text())
    if data != manifest():
        raise ValueError('DIS-009 source scope or numeric/QC/signature exclusion changed')
    pdf = root / PDF
    if not pdf.is_file() or hashlib.sha256(pdf.read_bytes()).hexdigest() != PDF_SHA:
        raise ValueError('DIS-009 primary PDF changed or is missing')
    if json.loads((root / SOURCE).read_text()) != records():
        raise ValueError('DIS-009 Table 2 values, SD, intervals or exclusion changed')
    return data


def render(root=None):
    data = verify(root)
    if data is None:
        return ''
    esc = html.escape
    body = ['<details><summary>DIS-009: verified Table 2 (12 group estimates)</summary>',
            '<p>' + esc(SCOPE) + '</p>', '<div style="overflow:auto"><table><thead><tr>',
            '<th>Hippocampus</th><th>Interval</th><th>Control mean (SD), n=20</th>',
            '<th>AD mean (SD), n=36</th><th>AD versus control p</th></tr></thead><tbody>']
    for side, months, hc, hs, ad, ads, relation in TABLE:
        values = [side, f'{months} months', f'{hc:.2f} ({hs:.2f}) %/year',
                  f'{ad:.2f} ({ads:.2f}) %/year', relation + '0.0001']
        body.append('<tr>' + ''.join('<td>' + esc(v) + '</td>' for v in values) + '</tr>')
    body.append('</tbody></table></div>')
    for field in ('table_location','total_definition','annualization','anatomical_definition',
                  'source_text_discrepancy','conclusion','counting_policy'):
        body.append('<p>' + esc(data[field]) + '</p>')
    body.append('<p>The exact annualization equation, days-per-year convention and 6-month scan-pair aggregation are not specified in this paper; no values are inferred.</p></details>')
    return ''.join(body)
