"""Join every source record to patient measurements without imputing diagnoses."""
import html
import json
import math
from pathlib import Path
import pandas as pd
from evidence_readiness import compatibility, known
from literature_audit import evidence_is_rejected
from zheng_exploratory import feature_key, compare
from comparison_atlas import comparison_features, translate_records, mapping_error
from reference_focus import pd_only, pd_table


def exploratory_results(result, frame, subject_id):
    """Reuse the actual paired comparison, rather than infer use from approval."""
    if pd_only(result) or not result.get('project_dir'):
        return {}
    path = Path(result['project_dir']) / 'workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json'
    if not path.exists():
        return {}
    comparison = compare(frame.to_dict('records'), json.loads(path.read_text()), subject_id)
    return {(r['doi'], r['roi'], r['hemisphere'], r['metric']): r
            for r in comparison['features']}


def ledger(result, subject_id):
    if pd_only(result):
        return pd_table(result, subject_id)
    frame = comparison_features(result)
    patient = frame.loc[frame.subject_id.eq(subject_id)]
    if patient.empty:
        raise ValueError('Subject absent: ' + subject_id)
    computed = exploratory_results(result, frame, subject_id)
    index = {}
    for row in patient.to_dict('records'):
        if not mapping_error(row):
            index.setdefault(feature_key(row), []).append(row)
    rows = []
    references = translate_records(result['literature_audit']['evidence'].to_dict('records'), patient.iloc[0]['comparison_registry'])
    for ref in references:
        matches = [] if mapping_error(ref) else index.get(feature_key(ref), [])
        entry = dict(subject_id=subject_id, evidence_id=ref['evidence_id'], paper_id=ref['paper_id'],
            paper_code=ref.get('paper_code'), doi=ref.get('doi'), source_title=ref.get('source_title'),
            roi_name=ref.get('roi_name'), hemisphere=ref.get('hemisphere'),
            imaging_metric=ref.get('imaging_metric'), reference_group=ref.get('diagnosis'),
            source_location=ref.get('source_location'), source_statement=ref.get('evidence_note'),
            review_status=ref.get('manual_review_status'), observed=None, unit=None,
            matched_patient_features=len(matches), within_individual_range=None,
            comparison_performed=False, reference_mean=None, reference_sd=None,
            observed_minus_mean=None, exploratory_z=None,
            log_density_ratio_AD_Control=None, closer_distribution=None,
            age_applicable=None,
            diagnostic_probability=None)
        reasons = []
        if evidence_is_rejected(ref):
            reasons.append('Source explicitly rejected')
        if len(matches) != 1:
            reasons.append('No exact ROI x hemisphere x metric match' if not matches else 'Ambiguous patient feature')
        else:
            p = matches[0]
            entry.update(observed=p.get('value_numeric'), unit=p.get('unit'))
            reasons.extend(compatibility(p, ref))
        if ref.get('manual_review_status') != 'accepted':
            reasons.append('New source extraction requires review')
        if not known(ref.get('roi_name')):
            reasons.append('Clinical criteria or source context; not an individual MRI measurement')
        # A group mean/SD or diagnostic sensitivity is not a validated individual interval.
        if ref.get('reference_interval_type') != 'individual_95pi':
            reasons.append('No verified 95% individual prediction interval')
        if ref.get('interval_applicability_verified') is not True:
            reasons.append('Individual interval applicability not verified')
        try:
            lo, hi = float(ref.get('reference_lower')), float(ref.get('reference_upper'))
            if not math.isfinite(lo) or not math.isfinite(hi) or lo > hi:
                raise ValueError()
        except (TypeError, ValueError):
            lo = hi = None
            reasons.append('Individual interval bounds absent or invalid')
        if not reasons:
            try:
                x = float(entry['observed'])
                if not math.isfinite(x):
                    raise ValueError()
                entry['within_individual_range'] = lo <= x <= hi
            except (TypeError, ValueError):
                reasons.append('Patient value nonfinite')
        entry['use_status'] = 'individual_range_comparison' if not reasons else (
            'excluded' if evidence_is_rejected(ref) else 'context_only' if not matches else 'not_harmonized')
        paired = computed.get((ref.get('doi'), *feature_key(ref)))
        group = ref.get('diagnosis')
        # Approval enables research use, not invented intervals or unit conversions.
        if (paired and group in ('AD', 'Control') and len(matches) == 1
                and not evidence_is_rejected(ref) and ref.get('manual_review_status') == 'accepted'
                and ref.get('unit') == matches[0].get('unit') == paired['unit']):
            entry.update(comparison_performed=True,
                         reference_mean=paired[group + '_mean'], reference_sd=paired[group + '_sd'],
                         observed_minus_mean=paired['observed'] - paired[group + '_mean'],
                         exploratory_z=paired[group + '_z'],
                         log_density_ratio_AD_Control=paired['log_density_ratio_AD_Control'],
                         closer_distribution=paired['closer_density'], age_applicable=paired['age_applicable'])
            if entry['use_status'] != 'individual_range_comparison':
                entry['use_status'] = 'exploratory_distribution_comparison'
        elif entry['use_status'] == 'individual_range_comparison':
            entry['comparison_performed'] = True
        entry['applicability_reasons'] = '; '.join(dict.fromkeys(reasons))
        rows.append(entry)
    return pd.DataFrame(rows)


def render_ledger(result, subject_id):
    if pd_only(result):
        from pd_evidence import render_pd
        return render_pd(result, subject_id)
    frame = ledger(result, subject_id)
    n = len(frame)
    matched = int(frame.matched_patient_features.eq(1).sum())
    usable = int(frame.use_status.eq('individual_range_comparison').sum())
    exploratory = int(frame.use_status.eq('exploratory_distribution_comparison').sum())
    # Count source rows, not unique patient ROIs or independent diagnostic votes.
    out = [f'<h4>Patient-linked source evidence | {html.escape(subject_id)}</h4>',
           f'<p>{n} source records checked; {matched} exact feature matches; '
           f'{exploratory} performed exploratory distribution comparisons; '
           f'{usable} eligible individual-range comparisons. Counts are source records, not patient ROIs: '
           'an AD and a Control reference for one measurement count as two source comparisons.</p>',
           '<p>Matching a feature is not diagnostic support by itself. Group distributions remain '
           'exploratory; absent or incompatible evidence neither excludes disease nor establishes Control.</p>']
    out.append('<details><summary>Source-by-source applicability summary</summary>')
    summary = frame.groupby(['paper_id', 'source_title', 'use_status'], dropna=False).size().reset_index(name='source_records')
    out.append(summary[['source_title', 'use_status', 'source_records']].to_html(index=False, escape=True, na_rep='Unavailable'))
    out.append('<p>Full patient values, source locations and reasons: Research details / Patient source evidence, '
               'or the exported patient_evidence CSV.</p>')
    out.append('</details>')
    return ''.join(out)


def export_ledger(result, subject_id, output_dir):
    if Path(subject_id).name != subject_id:
        raise ValueError('Invalid subject ID')
    out = Path(output_dir) / 'patient_evidence'
    out.mkdir(parents=True, exist_ok=True)
    path = out / (subject_id + '_source_evidence.csv')
    ledger(result, subject_id).to_csv(path, index=False)
    return path
