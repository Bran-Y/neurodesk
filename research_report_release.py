"""Final research dispositions, separate from historical human signatures and QC."""
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

BARNES_DOI = '10.1159/000084560'
HISTORY_COLUMNS = {
    'review_status', 'human_review_status', 'manual_review_status',
    'historical_review_status', 'source_review_status', 'case_review_status',
    'extraction_status', 'approval_record', 'raw_source_values',
}


def disposition(row):
    """State permitted use, not a made-up reviewer acceptance."""
    if any(str(row.get(k, '')).strip().lower() == 'rejected' for k in HISTORY_COLUMNS):
        return 'Excluded: recorded rejection'
    from covariate_fulltext_review import DOI as COVARIATE_DOI, verify as verify_covariate
    if str(row.get('doi','')).lower() == COVARIATE_DOI and verify_covariate() is not None:
        return 'Verified covariate associations with published inconsistencies; not a patient prediction model'
    if row.get('direction_eligible') is False or str(row.get('direction_eligible')).lower() == 'false':
        return 'Excluded from directional interpretation: conflicting source values'
    if str(row.get('doi', '')).lower() == BARNES_DOI:
        from barnes_fulltext_review import verify
        if verify() is not None:
            return 'Verified full-text statistics; context only, not a patient reference'
        return 'Verified abstract statistics; context only, not a patient reference'
    from dis009_fulltext_review import DOI, verify as verify_dis009
    if str(row.get('doi','')).lower() == DOI and verify_dis009() is not None:
        return 'Verified full-text longitudinal statistics; context only, not a single-scan patient reference'
    from dis006_fulltext_review import DOI as APOE_DOI, verify as verify_dis006
    if str(row.get('doi','')).lower() == APOE_DOI and verify_dis006() is not None:
        return 'Verified full-text APOE-stratified statistics; context only, not a patient reference'
    from dis011_fulltext_review import DOI as FTLD_DOI, verify as verify_dis011
    if str(row.get('doi','')).lower() == FTLD_DOI and verify_dis011() is not None:
        return 'Verified FTLD lobar context; not a single-parcel disease classifier'
    from hippocampal_fulltext_review import DOIS, verify as verify_hippocampal
    if str(row.get('doi','')).lower() in DOIS.values() and verify_hippocampal() is not None:
        return 'Verified longitudinal hippocampal context; not a single-scan patient reference'
    status = row.get('comparison_status', row.get('match_status', row.get('use_status', '')))
    if status in ('requires_followup', 'longitudinal_change'):
        return 'Not applicable to the current single-scan analysis'
    if status in ('not_comparable', 'unavailable', 'transformation_not_defined',
                  'surface_definition_mismatch', 'not_harmonized', 'excluded', 'not_approved'):
        return 'Excluded from numerical interpretation in this analysis'
    if status in ('matched_for_context', 'context_only'):
        return 'Context only; not individual diagnostic evidence'
    if status in ('descriptive_difference', 'exploratory_distribution_comparison'):
        return 'Descriptive research comparison; not a validated diagnosis'
    if status == 'individual_range_comparison':
        return 'Individual-range comparison with recorded applicability gates'
    if any(str(row.get(k, '')).lower() == 'accepted' for k in
           ('human_review_status', 'manual_review_status', 'source_review_status', 'review_status')):
        return 'Recorded source permission; measurement applicability remains separate'
    return 'Not used for numerical interpretation: approval/applicability not established'


def final_frame(frame):
    """Only change presentation copies; source/history files and exported values stay intact."""
    output = frame.copy(deep=True)
    if HISTORY_COLUMNS.intersection(output.columns):
        output['evidence_disposition'] = [disposition(row) for row in output.to_dict('records')]
        output = output.drop(columns=list(HISTORY_COLUMNS.intersection(output.columns)))
    if 'doi' in output and output.doi.eq(BARNES_DOI).any():
        from barnes_fulltext_review import verify
        data = verify()
        barnes = output.doi.eq(BARNES_DOI)
        reason = data['permitted_use'] if data else (
            'Excluded from numerical interpretation: abstract-only statistics; '
            'asymmetry formula/processing equivalence unverified; annual change requires serial scans.')
        for field in ('applicability_reasons', 'applicability_note', 'zero_match_reason'):
            if field in output:
                output.loc[barnes, field] = reason
        if data and 'source_check_status' in output:
            output.loc[barnes, 'source_check_status'] = 'primary_fulltext_statistics_verified_context_only'
    return output


def assert_final_text(content):
    if re.search(r'\bdraft\b|pending[_ -](?:human[_ -])?review|source_checked_pending', content, re.I):
        raise ValueError('Unresolved non-QC review wording remains in final presentation')


def verify_barnes(records):
    expected = [
        ('BARNES2005-HC-ASYMMETRY', 1.7, -.3, 3.7, 50),
        ('BARNES2005-AD-BASELINE-ASYMMETRY', 1.8, -1.9, 5.5, 32),
        ('BARNES2005-HC-LH-ATROPHY', 1.2, .5, 1.8, 50),
        ('BARNES2005-HC-RH-ATROPHY', 1.1, .5, 1.8, 50),
        ('BARNES2005-AD-LH-ATROPHY', 4.6, 3.3, 6.0, 32),
        ('BARNES2005-AD-RH-ATROPHY', 6.3, 4.9, 7.8, 32),
    ]
    values = [(r['record_id'], r['reported_value'], r['confidence_interval_lower'],
               r['confidence_interval_upper'], r['cohort_sample_size']) for r in records]
    if values != expected or any(r['doi'] != BARNES_DOI or r['numeric_use'] is not False or
                                r['comparison_compatible'] is not False or
                                r['standard_deviation'] is not None for r in records):
        raise ValueError('Barnes abstract statistics or exclusion guard changed')


def audit_sources(root):
    """Fail closed on new/unresolved records rather than silently relabeling them."""
    from literature_audit import build_literature_audit
    from resolve_enigma_sources import CORRECTIONS, CONFLICT_ID, PDF_SHA
    from zero_paper_review import review_for
    root = Path(root)
    audit = build_literature_audit(root)
    main = audit['evidence']
    nonaccepted = main.loc[main.manual_review_status.ne('accepted')]
    from dis009_fulltext_review import DOI, verify as verify_dis009
    dis009 = verify_dis009(root)
    dis009_rows = nonaccepted.loc[nonaccepted.doi.eq(DOI)]
    from dis006_fulltext_review import DOI as APOE_DOI, verify as verify_dis006
    dis006 = verify_dis006(root)
    dis006_rows = nonaccepted.loc[nonaccepted.doi.eq(APOE_DOI)]
    from dis011_fulltext_review import DOI as FTLD_DOI, verify as verify_dis011
    dis011 = verify_dis011(root)
    dis011_rows = nonaccepted.loc[nonaccepted.doi.eq(FTLD_DOI)]
    from hippocampal_fulltext_review import DOIS, verify as verify_hippocampal
    hippocampal = verify_hippocampal(root)
    hippocampal_rows = nonaccepted.loc[nonaccepted.doi.isin(DOIS.values())]
    from covariate_fulltext_review import DOI as COVARIATE_DOI, verify as verify_covariate
    covariate = verify_covariate(root)
    covariate_rows = nonaccepted.loc[nonaccepted.doi.eq(COVARIATE_DOI)]
    old_rows = nonaccepted.loc[nonaccepted.doi.eq(BARNES_DOI)]
    if (len(old_rows) != 6 or len(dis009_rows) != (12 if dis009 else 0)
            or len(dis006_rows) != (192 if dis006 else 0)
            or len(dis011_rows) != (42 if dis011 else 0)
            or len(hippocampal_rows) != (9 if hippocampal else 0)
            or len(covariate_rows) != (56 if covariate else 0)
            or len(nonaccepted) != len(old_rows) + len(dis009_rows) + len(dis006_rows) + len(dis011_rows) + len(hippocampal_rows) + len(covariate_rows)):
        raise ValueError('Unexpected main-source review items; inspect before release')
    barnes_path = root / 'workflow_sources/paper_reading_reviews/barnes_2005_reported_statistics.json'
    verify_barnes(json.loads(barnes_path.read_text()))
    catalog = [dict(doi=p['doi'], title=p['source_title'], **review_for(p))
               for p in audit['papers'].to_dict('records')]
    folder = root / 'workflow_sources/Disease/PD'
    source_check = json.loads((root / 'outputs/pending_review_20261004/enigma_source_technical_review.json').read_text())
    pdf_sha = hashlib.sha256((folder / 'raw/mds28706-sup-0001-supinfo.pdf').read_bytes()).hexdigest()
    if pdf_sha != PDF_SHA or any(
            hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest
            for name, digest in source_check['source_store_sha256'].items()):
        raise ValueError('Previously inspected primary PDF or canonical source store changed')
    if (source_check['total_rows'] != 760 or len(source_check['records']) != 760 or
            any(r['differences'] or r['fields_checked'] != 9 for r in source_check['records'])):
        raise ValueError('Source-bound primary PDF field review is incomplete')
    if (source_check['source_pdf_sha256'] != PDF_SHA or
            source_check['current_structured_field_difference_rows'] != 0 or
            source_check['direction_withheld_rows'] != 1):
        raise ValueError('ENIGMA canonical values/exclusion changed')
    whole = {r['evidence_id']: r for r in json.loads((folder / 'enigma_pd_group_statistics.json').read_text())['records']}
    for eid, (field, previous, value, page) in CORRECTIONS.items():
        if whole[eid][field] != value or whole[eid]['direction_eligible'] is not True:
            raise ValueError('Primary-source correction not installed: ' + eid)
    stage = {r['evidence_id']: r for r in json.loads((folder / 'enigma_pd_stage_statistics.json').read_text())['records']}
    if stage[CONFLICT_ID]['direction_eligible'] is not False:
        raise ValueError('Published sign conflict must remain excluded')
    approvals = json.loads((root / 'workflow_sources/paper_reading_reviews/pd_paper_review_approvals.json').read_text())
    permitted = {r['doi'] for r in approvals['papers'] if r.get('human_review_status') == 'accepted'
                 and r.get('data_use_status') == 'user_approved_research_use'}
    sources = json.loads((folder / 'reviewed_pd_quantitative_tables.json').read_text())['sources']
    if len(sources) != 4 or any(s['doi'] not in permitted for s in sources):
        raise ValueError('Additional PD paper permission missing')
    counts = {s['doi']: len(s['records']) for s in sources}
    if sorted(counts.values()) != [25, 44, 84, 85]:
        raise ValueError('Additional PD extraction inventory changed')
    signs = [r['evidence_id'] for s in sources for r in s['records']
             if r.get('mean') is not None and r.get('percent_change') is not None
             and r['mean'] * r['percent_change'] < 0]
    result = dict(main_records=len(main), recorded_human_permissions=len(main)-len(nonaccepted),
        fulltext_longitudinal_context_records=len(dis009_rows),
        fulltext_apoe_context_records=len(dis006_rows),
        fulltext_ftld_lobar_context_records=len(dis011_rows),
        fulltext_hippocampal_context_records=len(hippocampal_rows),
        fulltext_covariate_context_records=len(covariate_rows),
        abstract_records_context_only=6, canonical_enigma_rows=760,
        corrected_primary_source_fields=len(CORRECTIONS), excluded_direction=CONFLICT_ID,
        additional_pd_records=counts, additional_sign_conflicts_excluded_from_single_scan=signs,
        current_analysis_source_dispositions_complete=True,
        human_signatures_changed=False, patient_qc_changed=False, catalog=catalog,
        enigma_verification_method='Fresh SHA256 binding check against the retained 760-row primary-PDF field review; not a new independent extraction',
        barnes_verified_source='https://pubmed.ncbi.nlm.nih.gov/15785035/',
        barnes_extraction_sha256=hashlib.sha256(barnes_path.read_bytes()).hexdigest())
    from source_value_verification import verify
    result['completed_source_value_checks'] = verify(root)
    from hanganu_figure_review import verify as verify_figures
    result['completed_hanganu_figure_check'] = verify_figures(root)
    from barnes_fulltext_review import verify as verify_fulltext
    result['completed_barnes_fulltext_check'] = verify_fulltext(root)
    result['completed_dis009_fulltext_check'] = dis009
    result['completed_dis006_fulltext_check'] = dis006
    result['completed_dis011_fulltext_check'] = dis011
    result['completed_hippocampal_fulltext_check'] = hippocampal
    result['completed_covariate_fulltext_check'] = covariate
    return result
