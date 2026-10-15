"""Explicit research readiness, independent of expected patient diagnosis."""
import html
import json
import math
from pathlib import Path
import pandas as pd
from zheng_exploratory import compare, feature_key
from comparison_atlas import comparison_features, translate_records, mapping_error


def known(value):
    return value is not None and str(value).strip().lower() not in (
        '', 'nan', 'none', 'unknown', 'not reported', 'not recorded')


def compatibility(patient, reference):
    registry = patient.get('comparison_registry')
    patient, reference = translate_records([patient, reference], registry)
    reasons = []
    for role, row in [('Patient', patient), ('Reference', reference)]:
        if mapping_error(row):
            reasons.append(role + ': ' + mapping_error(row))
        if row.get('atlas_translation_review_status') != 'reviewed_quantitative_ready' or row.get('mapping_relation') != 'exact':
            reasons.append(role + ' atlas mapping not quantitatively approved')
    if reference.get('human_review_status') != 'accepted':
        reasons.append('Source review not accepted')
    if reference.get('comparison_compatible') is not True:
        reasons.append('Source not approved for harmonized numerical comparison')
    for field in ('standard_hemisphere', 'standard_imaging_metric', 'unit'):
        if not known(patient.get(field)) or patient.get(field) != reference.get(field):
            reasons.append(field + ' missing or mismatched')
    if feature_key(patient)[0] != feature_key(reference)[0]:
        reasons.append('ROI identity mismatch')
    for field in ('comparison_atlas_code', 'processing_software_version', 'normalization_method'):
        if not known(patient.get(field)) or not known(reference.get(field)):
            reasons.append(field + ' verification missing')
        elif patient[field] != reference[field]:
            reasons.append(field + ' mismatch')
    if reference.get('roi_boundary_verified') is not True:
        reasons.append('ROI boundary equivalence not verified')
    try:
        age, lo, hi = [float(v) for v in (patient.get('age'), reference.get('reference_age_min'), reference.get('reference_age_max'))]
        if not all(math.isfinite(v) for v in (age, lo, hi)) or not lo <= age <= hi:
            reasons.append('Outside reference age coverage; not disease exclusion')
    except (TypeError, ValueError):
        reasons.append('Reference age applicability unknown')
    return reasons


def reference_checks(result, sid):
    from reference_focus import pd_only, pd_table
    if pd_only(result):
        return pd_table(result, sid)
    path = Path(result['project_dir']) / 'workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json'
    refs = json.loads(path.read_text()) if path.exists() else []
    frame = comparison_features(result)
    patient = frame.loc[frame.subject_id.eq(sid)].to_dict('records')
    refs = translate_records(refs, frame.iloc[0]['comparison_registry'] if len(frame) else None)
    index = {}
    for row in refs:
        if not mapping_error(row):
            index.setdefault(feature_key(row), []).append(row)
    records = []
    for row in patient:
        matches = [] if mapping_error(row) else index.get(feature_key(row), [])
        if not matches:
            records.append(dict(subject_id=sid, roi_name=row['roi_name'], hemisphere=row['hemisphere'],
                imaging_metric=row['imaging_metric'], group=None, status='unavailable', reasons='No matched reference'))
        for ref in matches:
            reasons = compatibility(row, ref)
            records.append(dict(subject_id=sid, roi_name=row['roi_name'], hemisphere=row['hemisphere'],
                imaging_metric=row['imaging_metric'], group=ref.get('diagnosis'), doi=ref.get('doi'),
                status='exploratory_only' if reasons else 'compatible_not_clinically_validated',
                reasons='; '.join(reasons)))
    return pd.DataFrame(records)


def worklist(result):
    papers = result['papers']
    rows = []
    for _, p in papers.iterrows():
        if p.unique_evidence_rows == 0:
            from zero_paper_review import review_for
            decision = review_for(p.to_dict())
            rows.append(dict(paper=p.source_title, doi=p.doi,
                status='Source applicability assessed for current analysis',
                scope=decision['source_review_scope'],
                disposition=decision['finding'], permitted_use=decision['permitted_use']))
    return pd.DataFrame(rows)


def review_queue(result):
    frame = result['literature_audit']['evidence']
    frame = frame.loc[~frame.manual_review_status.eq('accepted')]
    from research_report_release import final_frame
    cols = ['paper_code', 'evidence_id', 'roi_name', 'evidence_note', 'source_url',
            'source_location', 'extraction_method', 'manual_review_status']
    return final_frame(frame[[c for c in cols if c in frame] +
                             (['doi'] if 'doi' in frame else [])])


def differential(result, sid):
    from reference_focus import pd_only, pd_table
    if pd_only(result):
        return pd_table(result, sid)
    path = Path(result['project_dir']) / 'workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json'
    refs = json.loads(path.read_text()) if path.exists() else []
    comparison = compare(comparison_features(result).to_dict('records'), refs, sid)
    records = []
    for group, opposite in [('AD', 'Control'), ('Control', 'AD')]:
        rows = comparison['features']
        records.append(dict(subject_id=sid, reference_group=group,
            higher_density_this_reference=sum(r['closer_density'] == group for r in rows),
            higher_density_other_reference=sum(r['closer_density'] == opposite for r in rows),
            ties=sum(r['closer_density'] == 'Tie' for r in rows),
            atypical_both=sum(r['atypical_both'] for r in rows),
            common_features=len(rows),
            status='Exploratory density comparison; not diagnostic probability',
            limitations='; '.join(comparison['warnings']) or comparison['limitations']))
    for group in ('MCI', 'FTD', 'VaD'):
        records.append(dict(subject_id=sid, reference_group=group, higher_density_this_reference=None,
            higher_density_other_reference=None, ties=None, atypical_both=None, common_features=None,
            status='Not evaluated', limitations='No validated matched comparator in this analysis; not exclusion'))
    return pd.DataFrame(records)


def readiness_html(result, sid):
    from reference_focus import pd_only
    if pd_only(result):
        return ('<h4>PD reference applicability</h4><p>ENIGMA PD versus Control group effects '
                'are compared with measured features and Potvin normative deviations through Atlas Translation. '
                'These are not individual PD reference distributions or a validated PD classifier. '
                'Normal-range findings do not exclude PD. Other diseases were not assessed in this scope.</p>')
    checks = reference_checks(result, sid)
    matched = checks.loc[checks.status.ne('unavailable')]
    blocked = sum(matched.status.ne('compatible_not_clinically_validated'))
    missing = sum(checks.status.eq('unavailable'))
    return ('<h4>Zheng comparison applicability | ' + html.escape(sid) + '</h4><p>' +
            str(blocked) + '/' + str(len(matched)) +
            ' matched feature-by-reference-group checks are exploratory only; ' + str(missing) +
            ' patient features have no matched Zheng reference. This does not describe Potvin normative coverage. '
            'See Research details: Compatibility and Reference comparison summary.</p>'
            '<p>No independent diagnostic validation or probability calibration has been completed. '
            'Normal-range findings do not establish Control; age mismatch does not exclude AD.</p>')
