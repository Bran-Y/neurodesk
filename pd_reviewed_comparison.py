"""Additional approved PD tables and explicitly typed patient comparisons."""
import html
import json
import math
from pathlib import Path

import pandas as pd

ASEG = {'Thalamus': 'Thalamus-Proper', 'Caudate': 'Caudate', 'Putamen': 'Putamen',
        'Pallidum': 'Pallidum', 'Hippocampus': 'Hippocampus', 'Amygdala': 'Amygdala',
        'Accumbens': 'Accumbens-area'}


def compare(result, subject_id):
    root = Path(result.get('project_dir', Path(__file__).parent))
    store = root / 'workflow_sources/Disease/PD/reviewed_pd_quantitative_tables.json'
    if not store.exists():
        return []
    approvals = root / 'workflow_sources/paper_reading_reviews/pd_paper_review_approvals.json'
    approved = {r['doi'] for r in json.loads(approvals.read_text())['papers']
                if r.get('human_review_status') == 'accepted' and
                r.get('data_use_status') == 'user_approved_research_use'} if approvals.exists() else set()
    features = result['features'].loc[result['features'].subject_id.eq(subject_id)]
    rows = []
    for source in json.loads(store.read_text())['sources']:
        for ref in source['records']:
            row = dict(subject_id=subject_id, paper=source['paper'], doi=source['doi'],
                evidence_id=ref['evidence_id'], source_table=ref['source_table'], source_row=ref['source_row'],
                record_kind=ref['record_kind'], structure=ref.get('structure'), group=ref.get('group'),
                hemisphere=ref.get('hemisphere'), reference_mean=ref.get('mean'), reference_sd=ref.get('sd'),
                reference_unit=ref.get('unit'), reference_version=source['processing_version'],
                reported_percent_change=ref.get('percent_change'), measured=None, difference_from_group_mean=None,
                source_warning='',
                comparison_status='context_only', comparison_reason='', human_review_status='accepted' if source['doi'] in approved else 'not_approved',
                raw_source_values=json.dumps(ref.get('raw'), ensure_ascii=True), source_url=source['source_url'])
            kind = ref['record_kind']
            if ref.get('mean') is not None and ref.get('percent_change') is not None and ref['mean'] * ref['percent_change'] < 0:
                row['source_warning'] = 'Mean change and reported percentage have opposite signs; both source values are retained, no sign correction inferred.'
            if source['doi'] not in approved:
                row.update(comparison_status='not_approved', comparison_reason='No accepted source-use record')
            elif kind == 'baseline_volume':
                side = {'lh': 'Left', 'rh': 'Right'}.get(ref.get('hemisphere'))
                suffix = ASEG.get(ref.get('structure'))
                name = side + '-' + suffix if side and suffix else ''
                matches = features.loc[features.roi_name.eq(name) & features.imaging_metric.eq('roi_volume') &
                    features.hemisphere.eq(ref.get('hemisphere')) & features.atlas_name.eq('FreeSurfer aseg')]
                reason = 'No unique native aseg feature' if len(matches) != 1 else ''
                if not reason:
                    patient = matches.iloc[0]
                    row['patient_version'] = str(patient.processing_software_version)
                    from segmentation_holds import reason as hold_reason
                    if hold_reason(patient):
                        reason = hold_reason(patient)
                    elif str(patient.processing_software_version).removesuffix('.0') != source['processing_version'].removesuffix('.0'):
                        reason = 'Processing-version mismatch'
                    elif patient.unit != 'mm3' or ref['unit'] != 'ml':
                        reason = 'Incompatible volume units'
                    elif not math.isfinite(float(patient.value_numeric)):
                        reason = 'Patient value is nonfinite'
                    else:
                        row['measured'] = float(patient.value_numeric) / 1000.0
                        row['difference_from_group_mean'] = row['measured'] - ref['mean']
                        row['patient_roi_name'] = name
                        row['unit_conversion'] = 'mm3 / 1000 = ml'
                row.update(comparison_status='not_comparable' if reason else 'descriptive_difference',
                    comparison_reason=reason or 'Raw group mean comparison only. Reference uses longitudinal initialization; current processing is cross-sectional. No covariate-adjusted Z score, diagnosis or reference interval.')
            elif kind == 'longitudinal_change':
                row.update(comparison_status='requires_followup',
                    comparison_reason='Two longitudinally processed scans and the reported time interval are required; a single absolute volume cannot be compared to change.')
            elif kind == 'vertex_cluster':
                row['comparison_reason'] = 'Published vertex-cluster statistics cannot be assigned to a whole DK parcel without the original cluster mask and surface registration.'
            elif kind == 'log_volume':
                row.update(comparison_status='transformation_not_defined',
                    comparison_reason='Published ventricle volumes are log-transformed. Base is unspecified; raw mm3 is not compared with log-volume means.')
            elif kind == 'pial_surface_area':
                row.update(comparison_status='surface_definition_mismatch',
                    comparison_reason='Reference is pial surface area; current aparc SurfArea is a white-surface measure. Do not substitute one for the other.')
            else:
                row['comparison_reason'] = 'Group association or qualitative map, not an individual measurement reference.'
            rows.append(row)
    return rows


def coverage(result, subject_id):
    rows = pd.DataFrame(compare(result, subject_id))
    if rows.empty:
        return pd.DataFrame(columns=['paper', 'doi', 'reference_records', 'descriptive_comparisons', 'followup_required', 'context_or_incompatible'])
    output = []
    for (paper, doi), frame in rows.groupby(['paper', 'doi'], sort=False):
        output.append(dict(paper=paper, doi=doi, reference_records=len(frame),
            descriptive_comparisons=int(frame.comparison_status.eq('descriptive_difference').sum()),
            followup_required=int(frame.comparison_status.eq('requires_followup').sum()),
            context_or_incompatible=int((~frame.comparison_status.isin(['descriptive_difference', 'requires_followup'])).sum())))
    return pd.DataFrame(output)


def render(result, subject_id, compact=False):
    frame = pd.DataFrame(compare(result, subject_id))
    if frame.empty:
        return '<p>Additional approved PD tables are not installed.</p>'
    columns = ['paper', 'source_table', 'evidence_id', 'structure', 'hemisphere', 'group',
               'measured', 'reference_mean', 'reference_sd', 'reference_unit', 'difference_from_group_mean',
               'comparison_status', 'comparison_reason', 'source_warning']
    summary = coverage(result, subject_id)
    differences = frame.loc[frame.comparison_status.eq('descriptive_difference'), columns]
    body = ['<h4>Four additional reviewed PD papers: quantitative comparisons</h4>',
        '<p>All imported records are retained, including non-significant findings. Approval is already recorded. '
        'Differences from group means are descriptive, not disease probabilities or normative Z scores. '
        'Current patient scans are cross-sectional; the Mak reference used longitudinal processing. '
        'Each structure is repeated for HC, PD-NC and PD-MCI; these are not independent votes.</p>',
        summary.to_html(index=False, escape=True, border=0),
        ('<details>' if compact else '<details open>') + '<summary>Baseline volume comparisons (ml)</summary><div style="overflow:auto;max-height:520px">',
        differences.to_html(index=False, escape=True, border=0), '</div></details>',
        '<details><summary>All additional PD records and comparability reasons</summary>'
        '<div style="overflow:auto;max-height:520px">', frame[columns].to_html(index=False, escape=True, border=0),
        '</div></details><p>Sources: ']
    for _, item in summary.iterrows():
        body.append('<a href="https://doi.org/' + html.escape(item.doi) + '">' + html.escape(item.paper) + '</a> ')
    body.append('</p>')
    if compact:
        body[0] = '<h4>Additional PD papers: quantitative comparisons</h4>'
        body[1] = (f'<p>{len(frame)} imported records; {len(differences)} descriptive baseline comparisons. '
                   'Group means are not individual reference ranges. Longitudinal, transformed and '
                   'cluster-only results remain separate.</p>')
    from source_value_verification import render as render_value_checks
    from hanganu_figure_review import render as render_figure_review
    root = Path(result.get('project_dir', Path(__file__).parent))
    return ''.join(body) + render_value_checks(root) + render_figure_review(root)


def export(result, subject_id, folder):
    folder = Path(folder)
    pd.DataFrame(compare(result, subject_id)).to_csv(folder / (subject_id + '_additional_pd_comparisons.csv'), index=False)
    coverage(result, subject_id).to_csv(folder / (subject_id + '_additional_pd_coverage.csv'), index=False)
