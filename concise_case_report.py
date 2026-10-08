"""Short, label-blind normative summary for the final workflow's Stage 8."""
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
from reference_focus import pd_only
from reference_range_overlap import render_range_overlap
from report_table_display import clean_missing_cells


def _text(value):
    return 'Not available' if pd.isna(value) or str(value).strip() == '' else str(value)


def _number(value):
    try:
        return f'{float(value):.3f}'.rstrip('0').rstrip('.') if pd.notna(value) else 'N/A'
    except (TypeError, ValueError):
        return 'N/A'


def exploratory_qc_held_summary(result, subject_id):
    """Show the measured-value sensitivity result when QC excludes a subject."""
    from segmentation_holds import reason

    if not pd_only(result):
        return ''
    features = result.get('comparison_features')
    if features is None or 'qc_hold_reason' not in features:
        return ''
    case = features.loc[features.subject_id.eq(subject_id)]
    if case.empty or not case.qc_hold_reason.map(lambda value: bool(reason({'qc_hold_reason': value}))).any():
        return ''

    from exploratory_pd_no_qc import unfiltered_copy
    from finished_evidence_workflow import resolve_required_files
    from mmc_normative_workflow import evaluate_features, load_models
    from pd_evidence import compare_result
    from pd_pattern_profile import profile, render as render_profile
    from potvin_subcortical import augment_normative

    root = Path(result.get('project_dir', Path(__file__).parent))
    unfiltered = unfiltered_copy(case)
    models = load_models(resolve_required_files(root)['mmc_models'])
    normative = evaluate_features(unfiltered, models)
    preview = dict(project_dir=root, comparison_features=unfiltered, normative=normative)
    preview['normative'] = augment_normative(preview, normative)
    valid = preview['normative'].calculation_status.eq('calculated')
    rows = compare_result(preview, subject_id)
    directional = profile(rows)
    return ('<section class="qc-unfiltered-research-preview">'
            '<h5>Exploratory comparison with the QC hold omitted</h5>'
            f'<p>{int(valid.sum())}/{len(valid)} normative measurements calculated; '
            f'{sum(row["match_status"] == "matched_for_context" for row in rows)}/{len(rows)} '
            'ENIGMA features matched. These measured values have not passed segmentation QC.</p>'
            + render_profile(directional) + '</section>')


def build_concise_report(result, subject_id):
    esc = html.escape
    features = result['features'].loc[result['features'].subject_id.eq(subject_id)]
    case = result['normative'].loc[result['normative'].subject_id.eq(subject_id)].copy()
    if features.empty or case.empty:
        raise ValueError(f'No feature/normative records for {subject_id}')
    demo = features.iloc[0]
    valid = case.loc[case.calculation_status.eq('calculated')].copy()
    statuses = valid.get('range_status', pd.Series(index=valid.index, dtype='object'))
    below, within, above = (int(statuses.eq(s).sum()) for s in
                            ('below_95pi', 'within_95pi', 'above_95pi'))
    if below + within + above != len(valid):
        raise ValueError('Calculated measurements have invalid range classifications')
    outside = valid.loc[statuses.isin(['below_95pi', 'above_95pi'])].copy()
    # Rank every abnormal measurement by deviation, with stable tie breakers.
    outside['_priority'] = pd.to_numeric(outside.get('zop', pd.Series(index=outside.index, dtype=float)), errors='coerce').abs()
    highlights = outside.sort_values(
        ['_priority', 'roi_name', 'hemisphere', 'imaging_metric'],
        ascending=[False, True, True, True], na_position='last').head(5)
    shown = highlights
    rows = []
    label = {'below_95pi': 'Below 95% PI', 'within_95pi': 'Within 95% PI',
             'above_95pi': 'Above 95% PI'}
    for _, row in shown.iterrows():
        calculated = row.calculation_status == 'calculated'
        interval = (f"{_number(row.get('lower_95pi'))} to {_number(row.get('upper_95pi'))}"
                    if calculated else 'N/A')
        rows.append({
            'ROI / side': f"{row.roi_name} / {row.hemisphere}",
            'Metric': row.imaging_metric,
            'Measured': f"{_number(row.get('observed_value'))} {_text(row.get('unit'))}",
            'Expected': _number(row.get('expected_value')) if calculated else 'N/A',
            '95% PI': interval,
            'Result': label.get(row.get('range_status'), 'Not assessed') if calculated else 'Not assessed',
        })
    demographics = demographic_summary(demo)
    from report_quality import qc_html
    report_state = 'Final research report'
    body = [f'<h3>Subject: {esc(subject_id)}</h3>', f'<p><b>{esc(report_state)}</b></p>']
    from report_interpretation import status_html
    body.append(status_html(compact=True))
    from segmentation_viewer import overlay_report_html, boundary_report_html
    try:
        body.append(overlay_report_html(result['fs_root'], subject_id,
                    Path(result.get('project_dir', '.')) / 'outputs/segmentation_overlay_cache'))
        body.append('<details><summary>Cortical and subcortical boundary overlays</summary>' +
                    boundary_report_html(result['fs_root'], subject_id,
                    Path(result.get('project_dir', '.')) / 'outputs/segmentation_overlay_cache') + '</details>')
    except (OSError, ValueError, ImportError) as exc:
        body.append('<p>Original MRI/mask overlay unavailable: ' + esc(str(exc)) + '</p>')
    body.append(qc_html(result, subject_id, compact=True))
    from segmentation_holds import hold_html
    body.append(hold_html(result, subject_id))
    body.extend(['<h4>Demographic</h4>', f'<p>{esc(demographics)}</p>'])
    body.extend(['<h4>Summary</h4>',
            f'<p>QC-eligible assessment: {len(valid)}/{len(case)} features assessed: '
            f'<b>{below} below, {within} within, {above} above</b> the 95% prediction interval; '
            f'{len(case) - len(valid)} not assessed.</p>'])
    from possible_disease_interpretation import from_result, render as render_possible_disease
    body.append(render_possible_disease(from_result(result, subject_id), compact=True))
    body.append(exploratory_qc_held_summary(result, subject_id))
    body.append('<h4>Quantitative / Potvin: highlighted deviations</h4>')
    if rows:
        body.append(pd.DataFrame(rows).to_html(index=False, escape=True, border=0))
    elif valid.empty:
        body.append('<p>No eligible normative measurements. No normality or disease conclusion is drawn.</p>')
    else:
        body.append('<p>No out-of-range measurements to highlight.</p>')
    body.append(f'<p class="note">{len(highlights)} of {len(outside)} deviations shown, ranked by '
                'absolute Zop; ties use ROI, hemisphere and metric. All measurements are retained below.</p>')
    body.append('<details><summary>All Potvin measurements (' + str(len(case)) + ' rows)</summary>'
                '<div style="overflow:auto;max-height:650px">' +
                measurement_table(case).to_html(index=False, escape=True, border=0) + '</div></details>')
    from workflow_audit import method_compatibility, source_coverage
    body.append('<details><summary>Atlas and processing-method compatibility</summary>' +
                method_compatibility(result, subject_id).to_html(index=False, escape=True, border=0) + '</details>')
    from cross_pipeline_review import render as render_cross_pipeline
    body.append(render_cross_pipeline(result, subject_id))
    coverage = source_coverage(result, subject_id)
    from research_report_release import final_frame
    coverage = final_frame(coverage)
    columns = ['source_title', 'doi', 'unique_evidence_rows', 'quantitative_records', 'reported_statistic_records', 'connected_group_effect_records',
               'matched_group_effect_features', 'stage_reference_records', 'matched_stage_features',
               'used_for_subject_qualitative', 'paired_features_exploratory', 'zero_evidence_reason', 'zero_match_reason']
    columns += [name for name in ('additional_quantitative_records', 'additional_descriptive_comparisons',
                                 'additional_followup_required') if name in coverage]
    body.append('<details><summary>Literature coverage and zero-count explanations</summary>'
                '<div style="overflow:auto">' + coverage[columns].to_html(index=False, escape=True, border=0) +
                '</div></details>')
    gaps = case.loc[case.calculation_status.ne('calculated')]
    if len(gaps):
        reasons = '; '.join(_text(v) for v in gaps.exclusion_reason.fillna('Reason not recorded').unique())
        body.append(f'<p class="note"><b>Not assessed:</b> {esc(reasons)}. '
                    'Missing reference coverage must not be interpreted as normality or atrophy.</p>')
    from pd_evidence import render_pd
    from pd_reviewed_comparison import render as render_reviewed_pd
    pd_content = render_pd(result, subject_id, compact=True) + render_reviewed_pd(result, subject_id, compact=True)
    body.append(pd_content if pd_only(result) else
                '<details><summary>PD reference comparisons (not a patient label)</summary>' + pd_content + '</details>')
    from zheng_exploratory import compare, render
    root = Path(result.get('project_dir', '.'))
    reference_path = root / 'workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json'
    if pd_only(result):
        body.append('<p><b>Reference focus: PD + Potvin.</b> AD/Control distribution comparison was not run.</p>')
    elif reference_path.exists():
        from comparison_atlas import comparison_features
        comparison = compare(comparison_features(result).to_dict('records'), json.loads(reference_path.read_text()), subject_id)
        body.append(render(comparison))
    else:
        body.append('<p>AD/Control comparison unavailable: supplementary reference file is missing.</p>')
    links = result['links']
    candidates = []
    if len(links):
        links = links.loc[links.subject_id.eq(subject_id)]
        for field in ('source_review_status', 'case_review_status'):
            if field in links:
                links = links.loc[~links[field].astype(str).str.strip().str.lower().eq('rejected')]
        keys = ['roi_name', 'hemisphere', 'imaging_metric']
        if len(outside):
            links = links.merge(outside[keys].drop_duplicates(), on=keys, how='inner')
        else:
            links = links.iloc[:0]
        candidates = links.drop_duplicates('paper_id').head(2).to_dict('records')
    body.append('<details><summary>Qualitative literature context</summary>')
    if candidates:
        body.append('<ul>')
        for ref in candidates:
            doi = ref.get('doi')
            citation = esc(_text(ref.get('source_title')))
            if pd.notna(doi) and str(doi).startswith('10.'):
                citation = f'<a href="https://doi.org/{quote(str(doi), safe="/")}">{citation}</a>'
            claim = _text(ref.get('literature_statement'))
            if len(claim) > 180:
                claim = claim[:177] + '...'
            case_review = _text(ref.get('case_review_status'))
            limitation = (' Case applicability not confirmed.' if case_review != 'accepted' else '')
            body.append(f'<li><b>{esc(_text(ref.get("roi_name")))}</b>: {esc(claim)} '
                        f'{citation}.{limitation}</li>')
        body.append('</ul><p class="note">ROI-linked context only, not confirmed agreement or disease evidence. '
                    'Full methods, evidence IDs and source locations: Stage 5–6.</p>')
    else:
        body.append('<p>No eligible source-linked context for out-of-range features. No disease inference.</p>')
    body.append('</details>')
    sources = []
    for doi in valid.get('source_doi', pd.Series(dtype=str)).dropna().unique():
        if str(doi).startswith('10.'):
            label = 'Potvin 2016 subcortical' if doi == '10.1016/j.neuroimage.2016.05.016' else 'Potvin cortical'
            sources.append('<a href="https://doi.org/' + quote(str(doi), safe='/') + '">' + label + '</a>')
    source = '; '.join(sources) or 'No applicable normative source calculated'
    body.append('<details><summary>Normative sources and statistical methods</summary>' +
                f'<p class="note">{source}. mmc1: cortical DK reference. '
                'mmc2: four eligible native aseg volumes (bilateral hippocampus/amygdala), '
                'independently checked against Calc formulas, not native Excel or clinical validation. '
                'Pointwise intervals; no multiple-comparison correction. '
                'Reference model FreeSurfer 5.3; verify the measurement processing version and segmentation QC.</p></details>')
    from mri_viewer import skull_stripped_report_html
    try:
        body.append('<details><summary>Skull-stripped MRI (additional view)</summary>' +
                    skull_stripped_report_html(subject_id, result['fs_root'],
                    Path(result.get('output_dir', root / 'finished_workflow_outputs')) / 'mri_cache') + '</details>')
    except (OSError, ValueError, ImportError, KeyError) as exc:
        body.append('<h4>Skull-stripped MRI</h4><p>MRI unavailable: ' + esc(str(exc)) +
                    '. Full-head T1 is not substituted.</p>')
    return clean_missing_cells('<section class="concise-case">' + ''.join(body) + '</section>')


def demographic_summary(demo):
    parts = [f"Age: {_number(demo.get('age'))}", f"Sex: {_text(demo.get('sex'))}"]
    for field, label in (('mmse', 'MMSE'), ('cdr', 'CDR')):
        value = _number(demo.get(field))
        if value != 'N/A':
            parts.append(f'{label}: {value}')
    return ' | '.join(parts)


def measurement_table(case):
    columns = ['roi_name', 'hemisphere', 'imaging_metric', 'observed_value', 'unit',
               'expected_value', 'lower_95pi', 'upper_95pi', 'zop',
               'calculation_status', 'range_status', 'exclusion_reason', 'source_doi']
    return case.sort_values(['roi_name', 'hemisphere', 'imaging_metric'])[
        [c for c in columns if c in case]].copy()


def export_concise_report(result, subject_id, output_dir):
    if Path(subject_id).name != subject_id:
        raise ValueError('Invalid subject ID')
    out = Path(output_dir) / 'concise_reports'
    out.mkdir(parents=True, exist_ok=True)
    content = build_concise_report(result, subject_id)
    case = result['normative'].loc[result['normative'].subject_id.eq(subject_id)]
    measurement_table(case).to_csv(out / f'{subject_id}_all_potvin_measurements.csv', index=False)
    from workflow_audit import export_subject_audits
    export_subject_audits(result, subject_id, out)
    from patient_evidence_ledger import export_ledger
    export_ledger(result, subject_id, output_dir)
    from pd_evidence import compare_result, compare_stage_result
    pd.DataFrame(compare_result(result, subject_id)).to_csv(
        out / f'{subject_id}_pd_source_comparisons.csv', index=False)
    pd.DataFrame(compare_stage_result(result, subject_id)).to_csv(
        out / f'{subject_id}_pd_stage_comparisons.csv', index=False)
    from pd_reviewed_comparison import export as export_reviewed_pd
    export_reviewed_pd(result, subject_id, out)
    from report_interpretation import export as export_interpretation
    export_interpretation(result, subject_id, out)
    path = out / f'{subject_id}_concise_report.html'
    style = 'body{font:14px Georgia,serif;max-width:1000px;margin:28px auto}table{border-collapse:collapse;width:100%}td,th{padding:6px;text-align:left;border-bottom:1px solid #ddd}.note{font-size:12px;color:#555}h4{margin:16px 0 6px}'
    snapshot = ('<p class="note">Saved research snapshot: ' + datetime.now(timezone.utc).isoformat() +
                ' | Scope: ' + html.escape(str(result.get('reference_focus', 'all'))) +
                '. Not a live report.</p>')
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write('<!doctype html><html><head><meta charset="utf-8"><title>' +
                     html.escape(subject_id) + ' concise report</title><style>' + style +
                     '</style></head><body>' + snapshot + content + '</body></html>')
    return path
