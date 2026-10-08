"""Auditable range membership, never a diagnostic probability.

References must supply reviewed individual-level intervals, not mean CIs.
Comparisons use the same feature set across groups within each source paper.
"""
import html
import json
import math
from pathlib import Path

import pandas as pd
from comparison_atlas import feature_key as key, prepare_features, translate_records, mapping_error


GROUPS = ('AD', 'Control', 'MCI')


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def text(value):
    return '' if value is None or (isinstance(value, float) and math.isnan(value)) else str(value).strip()


def compare_ranges(features, references, subject_id, groups=GROUPS):
    if 'comparison_registry' not in features:
        features = prepare_features(features)
    references = translate_records(references, features.iloc[0]['comparison_registry'] if len(features) else None)
    patient = features.loc[features.subject_id.eq(subject_id)]
    if patient.empty:
        raise ValueError(f'Subject not found: {subject_id}')
    measured = {}
    for row in patient.to_dict('records'):
        if not mapping_error(row):
            measured.setdefault(key(row), []).append(row)
    audit = []
    for index, ref in enumerate(references):
        if ref.get('diagnosis') not in groups:
            continue
        paper = text(ref.get('doi')) or text(ref.get('paper_code'))
        record = dict(subject_id=subject_id, paper=paper, reference_row=index,
                      reference_id=ref.get('reference_id'), group=ref['diagnosis'],
                      feature=' | '.join(key(ref)), source_title=ref.get('source_title'),
                      source_location=ref.get('source_location') or ref.get('table_or_figure'),
                      lower=ref.get('range_lower'), upper=ref.get('range_upper'),
                      unit=ref.get('unit'), observed=None, within=None)
        reasons = []
        if mapping_error(ref):
            reasons.append(mapping_error(ref))
        if ref.get('atlas_translation_review_status') != 'reviewed_quantitative_ready' or ref.get('mapping_relation') != 'exact':
            reasons.append('reference_atlas_mapping_not_approved')
        if not paper or not record['source_location']:
            reasons.append('source_location_missing')
        # Historic/AI verification is not current human approval.
        if ref.get('human_review_status') != 'accepted' or not text(ref.get('reviewed_by')) or not text(ref.get('reviewed_at')):
            reasons.append('human_approval_missing')
        if ref.get('comparison_compatible') is not True:
            reasons.append('compatibility_not_approved')
        lower, upper = number(ref.get('range_lower')), number(ref.get('range_upper'))
        if (lower is None or upper is None or lower >= upper or
                ref.get('range_type') not in ('individual_reference_interval', 'individual_prediction_interval') or
                not text(ref.get('range_source')) or number(ref.get('range_coverage')) != .95):
            reasons.append('reviewed_individual_95pct_range_missing')
        matches = [] if mapping_error(ref) else measured.get(key(ref), [])
        if len(matches) != 1:
            reasons.append('patient_feature_missing_or_duplicated')
        else:
            row = matches[0]
            if mapping_error(row):
                reasons.append(mapping_error(row))
            if row.get('atlas_translation_review_status') != 'reviewed_quantitative_ready' or row.get('mapping_relation') != 'exact':
                reasons.append('patient_atlas_mapping_not_approved')
            value = number(row.get('value_numeric'))
            record['observed'] = value
            if value is None:
                reasons.append('patient_value_missing')
            age, age_min, age_max = map(number, (row.get('age'), ref.get('reference_age_min'), ref.get('reference_age_max')))
            if age is None or age_min is None or age_max is None or age_min > age_max:
                reasons.append('age_applicability_missing')
            elif not age_min <= age <= age_max:
                reasons.append('age_outside_reference')
            for field, patient_field in [('unit', 'unit'), ('atlas_name', 'atlas_name'),
                                          ('atlas_version', 'atlas_version'),
                                          ('processing_pipeline', 'source_pipeline'),
                                          ('normalization_method', 'statistic_type')]:
                # Missing or unknown metadata never counts as a match.
                a, b = text(ref.get(field)), text(row.get(patient_field))
                if not a or not b or a.lower() != b.lower() or 'not reported' in a.lower():
                    reasons.append(field + '_incompatible_or_missing')
            from processing_compatibility import same_version
            if not same_version(row.get('processing_software_version'), ref.get('processing_software_version')):
                reasons.append('processing_software_version_incompatible_or_missing')
            sex = text(ref.get('reference_sex')).lower()
            if sex not in ('all', text(row.get('sex')).lower()) or not sex:
                reasons.append('sex_applicability_missing_or_mismatched')
            if not reasons:
                record['within'] = lower <= value <= upper
        record['exclusion_reason'] = '; '.join(reasons)
        record['eligible'] = not reasons
        audit.append(record)
    audit = pd.DataFrame(audit, columns=['subject_id','paper','reference_row','reference_id','group','feature',
        'source_title','source_location','lower','upper','unit','observed','within','exclusion_reason','eligible'])
    # Multiple references for the same study/group/feature cannot inflate counts.
    duplicate = audit.duplicated(['paper', 'group', 'feature'], keep=False)
    audit.loc[duplicate, 'eligible'] = False
    audit.loc[duplicate, 'exclusion_reason'] += '; duplicate_study_group_feature'
    summaries = []
    for paper in sorted(audit.paper.unique()):
        study = audit.loc[audit.paper.eq(paper)]
        sets = {g: set(study.loc[study.group.eq(g) & study.eligible, 'feature']) for g in groups}
        common = set.intersection(*sets.values())
        for group in groups:
            rows = study.loc[study.group.eq(group) & study.eligible & study.feature.isin(common)]
            hits, n = int(rows.within.sum()), len(common)
            summaries.append(dict(paper=paper, group=group, available_features=len(sets[group]),
                                  matching_features=hits, common_features=n,
                                  overlap_percent=100 * hits / n if n else None,
                                  status='calculated' if n else 'no_common_comparable_features'))
    summary = pd.DataFrame(summaries, columns=['paper','group','available_features','matching_features',
                                              'common_features','overlap_percent','status'])
    return summary, audit


def evaluation_record(subject_id, expectations):
    matches = [r for r in expectations.get('cases', []) if r['subject_id'] == subject_id]
    if len(matches) > 1:
        raise ValueError('Duplicate expected labels for ' + subject_id)
    return dict(subject_id=subject_id,
                expected_label=matches[0]['expected_label'] if matches else 'Not supplied',
                label_provenance=expectations.get('provenance', 'Not supplied'),
                independent_prediction=None, support_level='Not assessable',
                evaluation_status='Not yet validated',
                reason='No validated disease-discrimination rule; range membership alone cannot assign support levels.')


def render_range_overlap(features, references, subject_id, expectations=None):
    summary, audit = compare_ranges(features, references, subject_id)
    out = ['<h4>Reference-range applicability audit</h4>',
           '<p class="note">This audit concerns approved individual reference intervals. '
           'The separate exploratory AD/Control comparison uses group means and SDs, '
           'not these intervals. Neither provides a calibrated diagnostic probability.</p>',
           '<details><summary>Reference-range comparisons and applicability</summary>',
           '<p>Matching / common comparable features, separately by paper. '
           'The same ROI x hemisphere x metric set is used for AD, Control and MCI. '
           'Boundary values count as within; missing data never count as a mismatch. '
           'Percentages need not sum to 100% and do not rank diagnoses.</p>']
    usable = summary.loc[summary.status.eq('calculated')]
    if usable.empty:
        out.append('<p><b>Not calculable with the current references.</b> '
                   'No shared, approved 95% individual reference ranges across all three groups. '
                   'This is unavailable, not 0% agreement or exclusion of disease.</p>')
    else:
        out.append(usable.to_html(index=False, float_format=lambda x: f'{x:.1f}%', escape=True))
    with_details = ['<details><summary>Coverage, exclusions and source-level comparisons</summary>']
    with_details.append(summary.to_html(index=False, na_rep='N/A', escape=True))
    if not audit.empty:
        counts = audit.exclusion_reason.str.split('; ').explode()
        counts = counts[counts.ne('')].value_counts()
        with_details.append('<p>' + html.escape('; '.join(f'{k}: {v}' for k, v in counts.items())) + '</p>')
        with_details.append(audit.to_html(index=False, na_rep='N/A', escape=True))
    out.extend(with_details + ['</details>', '</details>'])
    return ''.join(out)


def load_reference_ranges(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError('Reference registry must be a list')
    return data
