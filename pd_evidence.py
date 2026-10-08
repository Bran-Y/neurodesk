"""PD group-effect context, kept separate from diagnosis and normative intervals."""
import html
import json
import math
import re
from pathlib import Path


def direction_context(status, effect):
    if status == 'within_95pi':
        return 'Within normative PI; neither confirms nor excludes PD'
    if status not in ('below_95pi', 'above_95pi') or not math.isfinite(effect) or effect == 0:
        return 'Not directionally assessed'
    same = (status == 'below_95pi') == (effect < 0)
    return ('Outside PI in the published group-effect direction' if same else
            'Outside PI opposite to the published group-effect direction')


def nominal_significance(value):
    """Read reported p bounds conservatively; this does not establish FDR significance."""
    match = re.fullmatch(r'\s*([<>]=?)?\s*([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*', str(value))
    if not match:
        return None
    bound, number = match.groups()
    p = float(number)
    if not 0 <= p <= 1:
        return None
    if not bound:
        return p < 0.05
    if bound == '<' and 0 < p <= 0.05 or bound == '<=' and p < 0.05:
        return True
    if bound in ('>', '>=') and p >= 0.05:
        return False
    return None


def reported_direction_context(status, effect, p_value):
    original = direction_context(status, effect)
    if not original.startswith('Outside PI'):
        return original
    significant = nominal_significance(p_value)
    if significant is True:
        return original + '; nominal p<0.05 only; corrected significance not established here'
    relation = 'same sign' if (status == 'below_95pi') == (effect < 0) else 'opposite sign'
    status_text = ('published effect not nominally significant (reported p >= 0.05)' if significant is False
                   else 'published significance unavailable or indeterminate')
    return 'Outside PI; ' + status_text + '; sign-only relation: ' + relation + '. Not disease support.'


def compare_records(patient, normative, references, subject_id, registry=None):
    from comparison_atlas import translate_records, feature_key, mapping_error
    patient = translate_records([r for r in patient if r['subject_id'] == subject_id], registry)
    references = translate_records(references, registry)
    index, norms = {}, {}
    from segmentation_holds import reason as hold_reason
    held = {feature_key(row): hold_reason(row) for row in patient if hold_reason(row)}
    for row in patient:
        if not mapping_error(row):
            index.setdefault(feature_key(row), []).append(row)
    for row in normative:
        if row['subject_id'] == subject_id:
            key = (row['roi_name'], row['hemisphere'], row['imaging_metric'])
            norms.setdefault(key, []).append(row)
    output = []
    for ref in references:
        matches = index.get(feature_key(ref), []) if not mapping_error(ref) else []
        reason = mapping_error(ref) or held.get(feature_key(ref), '') or ('No unique patient feature' if len(matches) != 1 else '')
        row = matches[0] if len(matches) == 1 else {}
        if row and row.get('comparison_atlas_code') != ref.get('comparison_atlas_code'):
            reason = 'Different native atlases; label alignment does not convert parcellations'
        if row and row.get('unit') != ref['unit']:
            reason = 'Measurement unit mismatch'
        if row and (str(row.get('processing_software_version')).removesuffix('.0') !=
                    str(ref.get('processing_software_version')).removesuffix('.0')):
            reason = 'Patient and reference processing versions differ'
        n = norms.get((row.get('roi_name'), row.get('hemisphere'), row.get('imaging_metric')), [])
        normal = n[0] if len(n) == 1 else {}
        state = normal.get('range_status') if normal.get('calculation_status') == 'calculated' else None
        effect = float(ref['effect_size'])
        output.append(dict(subject_id=subject_id, source_structure=ref['source_structure'],
                           standard_roi_name=ref.get('standard_roi_name'), hemisphere=ref['hemisphere'],
                           metric=ref['imaging_metric'], measured=row.get('value_numeric'), unit=ref['unit'],
                           normative_status=state if isinstance(state, str) else 'not_calculated',
                           expected_value=normal.get('expected_value') if state and not reason else None,
                           lower_95pi=normal.get('lower_95pi') if state and not reason else None,
                           upper_95pi=normal.get('upper_95pi') if state and not reason else None,
                           normative_zop=normal.get('zop') if state and not reason else None,
                           pd_minus_control_cohen_d=effect, p_as_reported=ref.get('p_value_as_reported'),
                           nominal_p_below_0_05=nominal_significance(ref.get('p_value_as_reported')),
                           corrected_significance_status='not_established_from_reported_raw_p',
                           n_pd=ref['n_patients'], n_control=ref['n_controls'],
                           context=('Not comparable: ' + reason if reason else
                                    'Published source discrepancy; directional comparison withheld'
                                    if not ref.get('direction_eligible', True) else reported_direction_context(state, effect, ref.get('p_value_as_reported'))),
                           match_status='unavailable' if reason else 'matched_for_context',
                           review_status=ref['human_review_status'], evidence_id=ref['evidence_id'],
                           doi=ref['doi'], source_data_url=ref['source_data_url'], source_line=ref.get('source_line'),
                           source_table=ref.get('source_table', ''), source_page=ref.get('source_page'),
                           comparison_group=ref.get('comparison_group', 'whole_sample'),
                           patient_roi_name=row.get('roi_name'),
                           patient_atlas=row.get('comparison_atlas_code'),
                           reference_atlas=ref.get('comparison_atlas_code'),
                           patient_processing_version=row.get('processing_software_version'),
                           reference_processing_version=ref.get('processing_software_version'),
                           mapping_method='same_native_atlas_label_alignment' if row and not reason else 'not_comparable',
                           regression_coefficient=ref.get('regression_coefficient'),
                           regression_standard_error=ref.get('regression_standard_error'),
                           regression_ci_lower=ref.get('regression_ci_lower'),
                           regression_ci_upper=ref.get('regression_ci_upper'),
                           regression_ci_target=ref.get('regression_ci_target'),
                           source_warning=ref.get('source_warning') or
                               ('PDF and TOOLBOX differ; see supplement audit' if ref.get('supplement_discrepancies') else ''),
                           direction_eligible=ref.get('direction_eligible', True)))
    return output


def compare_result(result, subject_id):
    from comparison_atlas import comparison_features
    root = Path(result.get('project_dir', Path(__file__).parent))
    path = root / 'workflow_sources/Disease/PD/enigma_pd_group_statistics.json'
    if not path.exists():
        return []
    return compare_records(comparison_features(result).to_dict('records'),
                           result['normative'].to_dict('records'), json.loads(path.read_text())['records'],
                           subject_id, root / 'workflow_sources/atlas_translation/atlas_translation_registry.json')


def compare_stage_result(result, subject_id):
    """Compare every reported HY stratum without assigning a stage to the patient."""
    from comparison_atlas import comparison_features
    root = Path(result.get('project_dir', Path(__file__).parent))
    path = root / 'workflow_sources/Disease/PD/enigma_pd_stage_statistics.json'
    if not path.exists():
        return []
    return compare_records(comparison_features(result).to_dict('records'),
                           result['normative'].to_dict('records'), json.loads(path.read_text())['records'],
                           subject_id, root / 'workflow_sources/atlas_translation/atlas_translation_registry.json')


def stage_context_payload(result, subject_id):
    """Keep repeated-study sensitivity analyses outside independent candidate evidence."""
    rows = compare_stage_result(result, subject_id)
    keys = ('standard_roi_name', 'hemisphere', 'metric', 'unit', 'normative_status',
            'pd_minus_control_cohen_d', 'comparison_group', 'source_table', 'source_page',
            'n_pd', 'n_control', 'context', 'source_warning', 'match_status')
    return dict(source='ENIGMA_PD', patient_stage='not_assigned',
                usage='Sensitivity context only; same study and overlapping controls. Do not count as independent votes or infer HY stage.',
                reference_rows=len(rows),
                comparisons=[{k: row[k] for k in keys} for row in rows
                             if row['normative_status'] in ('below_95pi', 'above_95pi')])


def render_stage_context(result, subject_id):
    import pandas as pd
    rows = compare_stage_result(result, subject_id)
    if not rows:
        return ''
    frame = pd.DataFrame(rows)
    cols = ['source_structure', 'metric', 'measured', 'normative_status', 'comparison_group',
            'pd_minus_control_cohen_d', 'p_as_reported', 'nominal_p_below_0_05', 'corrected_significance_status',
            'n_pd', 'n_control', 'context', 'source_table', 'source_page',
            'source_warning']
    outside = frame.normative_status.isin(['below_95pi', 'above_95pi'])
    highlights = (frame.loc[outside, cols].to_html(index=False, escape=True, border=0) if outside.any()
                  else '<p>No feature outside its available normative interval.</p>')
    return ('<h4>PD supplementary comparisons by published HY stage</h4>'
            f'<p>{len(rows)} stage-specific reference rows from Tables S4a-S4l. '
            'Each patient measurement is compared with HY1, HY2, HY3 and HY4-5 group effects. '
            'The patient HY stage is not assigned. These analyses reuse the same study and overlapping '
            'controls; they are not independent evidence or a disease progression prediction. '
            'Rows with source discrepancies are withheld from directional comparison.</p>'
            '<div style="overflow:auto;max-height:480px">' + highlights + '</div>'
            '<details><summary>All stage comparisons with source pages</summary>'
            '<div style="overflow:auto;max-height:480px">' + frame[cols].to_html(index=False, escape=True, border=0)
            + '</div></details><p>Reference: Laansma 2021 supplement, S4a-S4l, pages 11-26. '
            'S2/S4 confidence intervals describe adjusted group differences, not individual prediction intervals.</p>')


def render_pd(result, subject_id, compact=False):
    import pandas as pd
    rows = compare_result(result, subject_id)
    if not rows:
        return '<h4>PD evidence context</h4><p>PD source data unavailable.</p>'
    frame = pd.DataFrame(rows)
    from pd_pattern_profile import profile, render as render_profile
    pattern_html = render_profile(profile(rows))
    matched = frame.match_status.eq('matched_for_context').sum()
    eligible = frame.get('direction_eligible', pd.Series(True, index=frame.index))
    withheld = (~eligible.fillna(False).astype(bool)).sum()
    outside = frame.normative_status.isin(['below_95pi', 'above_95pi'])
    columns = ['source_structure', 'metric', 'measured', 'unit', 'normative_status',
               'pd_minus_control_cohen_d', 'p_as_reported', 'nominal_p_below_0_05', 'corrected_significance_status', 'context']
    intro = ('<h4>PD study references: published group-effect context</h4>'
             '<p>This heading identifies the reference studies, not this patient\'s diagnosis. '
             'No Possible PD candidate is generated from group-effect direction matching.</p>'
             f'<p>QC-eligible comparison: {matched}/{len(rows)} reference features matched by native-atlas label alignment. '
             f'{withheld} source-discrepant rows are withheld from directional interpretation. '
             'These are group effect sizes, not PD patient reference ranges or a PD diagnosis. '
             'Negative d means lower measurements in the PD group; positive d means higher.</p>'
             '<p>No clinical PD prediction is made. Normal-range MRI does not rule out PD. '
             'Direction matches are not independent votes, diagnostic probabilities, or significance tests. '
             'Reported p>=0.05 findings are retained as non-significant, sign-only comparisons, '
             'not PD-supporting or PD-excluding evidence. Nominal p<0.05 does not establish '
             'multiple-comparison-corrected significance. '
             'Native-atlas and processing-version compatibility is enforced; segmentation QC remains required. '
             'The ENIGMA cohort includes PPMI; overlap with the test participants is unresolved, '
             'so this is not independent validation.</p>')
    highlights = frame.loc[outside].reindex(columns=columns).to_html(index=False, escape=True, border=0)
    if not outside.any():
        highlights = '<p>No matched out-of-range feature available for directional context.</p>'
    if compact:
        from research_report_release import final_frame
        presented = final_frame(frame)
        return ('<h4>PD study references: published group-effect context</h4>'
                f'<p>QC-eligible comparison: {matched}/{len(rows)} reference features matched; '
                f'{int(outside.sum())} out-of-range comparisons; {withheld} source-discrepant rows withheld. '
                'Direction agreement is not a PD diagnosis.</p>' + pattern_html + highlights +
                '<details><summary>All PD source comparisons and provenance</summary>' +
                '<div role="region" aria-label="PD evidence table" tabindex="0" '
                'style="max-height:480px;overflow:auto">' +
                presented.to_html(index=False, escape=True, border=0) + '</div>' + intro +
                '<p>Source: <a href="https://doi.org/10.1002/mds.28706">Laansma et al., 2021</a>. '
                'Negative d: lower PD-group measurement; positive d: higher. '
                'Group CI/SE are not individual prediction intervals; PPMI overlap remains unresolved.</p></details>' +
                '<details><summary>HY-stage comparisons (patient stage not assigned)</summary>' +
                render_stage_context(result, subject_id) + '</details>')
    return (intro + pattern_html + highlights + '<details><summary>All PD source comparisons and provenance</summary>' +
            '<div role="region" aria-label="PD evidence table" tabindex="0" '
            'style="width:100%;max-height:480px;overflow:auto">' +
            frame.to_html(index=False, escape=True, border=0) + '</div></details>' +
            '<p>Source: <a href="https://doi.org/10.1002/mds.28706">Laansma et al., 2021</a>; '
            '<a href="https://enigma-toolbox.readthedocs.io/en/latest/pages/04.loadsumstats/#parkinson-s-disease">'
            'ENIGMA TOOLBOX PD summary statistics</a>. FreeSurfer 5.3; cortical DK and subcortical aseg. '
            'Published group-effect CI/SE columns are not used as individual 95% PI. '
            'Reference-study clinical data provenance (not patient group assignment): <a href="https://doi.org/10.1016/j.pneurobio.2011.09.005">'
            'PPMI study</a>. Additional individual-level reference data have not been downloaded.</p>' +
            render_stage_context(result, subject_id))
