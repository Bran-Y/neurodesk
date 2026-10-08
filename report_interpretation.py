"""Separate exploratory hypotheses from individual disease classification."""
import json
from pathlib import Path

POLICY_VERSION = 'regional-hypothesis-not-classification-v1'


def assessment(comparison=None, scope='all'):
    from zheng_exploratory import regional_candidate
    candidate = regional_candidate(comparison) if comparison is not None else False
    return dict(policy_version=POLICY_VERSION, reference_focus=scope,
        assigned_diagnosis=None, disease_probabilities=None,
        classification_status='not_estimated',
        exploratory_candidates=['AD-like regional pattern'] if candidate else [],
        candidate_rule='four_unique_bilateral_hippocampus_amygdala_volumes_higher_AD_marginal_density',
        candidate_rule_evaluated=comparison is not None,
        known_diagnosis_used_as_input=False,
        interpretation='Reference cohort labels, normative intervals and PD group-effect direction '
                       'matches are not individual disease classifications. Absence of a candidate '
                       'does not establish Control or exclude a disease.')


def status_html(compact=False):
    if compact:
        return ('<section class="classification-status" data-assigned-diagnosis="none">'
                '<h4>Patient disease classification</h4><p><b>Not estimated.</b> '
                'AD-like denotes a regional hypothesis, not an assigned diagnosis. '
                'AD, PD and Control in tables identify reference cohorts.</p></section>')
    return ('<section class="classification-status" data-assigned-diagnosis="none">'
            '<h4>Patient disease classification</h4><p><b>Not estimated.</b> '
            'AD-like is an exploratory regional hypothesis when its stated rule is met, '
            'not an assigned diagnosis. AD, PD and Control labels in comparison tables '
            'name reference cohorts, not this patient. Normal-range measurements do not '
            'establish Control; PD direction matches do not establish PD.</p></section>')


def export(result, sid, folder):
    from reference_focus import pd_only
    from zheng_exploratory import compare
    from comparison_atlas import comparison_features
    path = Path(result.get('project_dir', '.')) / 'workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json'
    comparison = None
    if not pd_only(result) and path.exists():
        comparison = compare(comparison_features(result).to_dict('records'), json.loads(path.read_text()), sid)
    record = dict(subject_id=sid, **assessment(comparison, result.get('reference_focus', 'all')))
    from possible_disease_interpretation import from_result
    record['possible_disease_interpretation'] = from_result(result, sid)
    target = Path(folder) / (sid + '_interpretation.json')
    target.write_text(json.dumps(record, indent=2, allow_nan=False))
    return record
