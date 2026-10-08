"""Literature-linked regional explanations, not a trained disease classifier."""
import html
import json
import math
from pathlib import Path
import re

AD_DOI = '10.1371/journal.pone.0279574'
PD_DOI = '10.1002/mds.28706'
REQUIRED_AD = {(roi, side) for roi in ('hippocampus', 'amygdala') for side in ('lh', 'rh')}
INTERPRETATION_SECTION = re.compile(
    r'<section class="possible-disease-interpretation"[^>]*>.*?</section>', re.S)


def finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def summarize(comparison=None, pd_rows=(), scope='all'):
    from zheng_exploratory import regional_candidate
    from pd_evidence import nominal_significance
    from pd_pattern_profile import profile, description
    pd_rows = list(pd_rows)
    directional_profile = profile(pd_rows)
    ad_rows = [] if comparison is None or scope == 'PD' else [
        row for row in comparison['features']
        if (row['roi'], row['hemisphere']) in REQUIRED_AD and row['metric'] == 'roi_volume']
    ad_candidate = (scope != 'PD' and comparison is not None and regional_candidate(comparison)
                    and all(row.get('doi') == AD_DOI for row in ad_rows))
    ad = dict(status='AD-like regional pattern' if ad_candidate else
              'Not assessed in PD-only scope' if scope == 'PD' else 'AD-like rule not met',
              candidate=ad_candidate, doi=AD_DOI, source_location='S1 AD / S2 Control',
              rule='All four distinct bilateral hippocampus/amygdala volumes have higher AD marginal density.',
              reasons=ad_rows, warnings=[] if comparison is None else comparison.get('warnings', []))
    eligible, withheld = {}, 0
    for row in pd_rows:
        valid = (row.get('doi') == PD_DOI and row.get('comparison_group') == 'whole_sample'
                 and row.get('match_status') == 'matched_for_context'
                 and row.get('direction_eligible') is True
                 and row.get('review_status') != 'rejected'
                 and row.get('mapping_method') == 'same_native_atlas_label_alignment'
                 and row.get('normative_status') in ('below_95pi', 'above_95pi')
                 and finite(row.get('measured')) and float(row['measured']) > 0
                 and finite(row.get('pd_minus_control_cohen_d'))
                 and float(row['pd_minus_control_cohen_d']) != 0
                 and nominal_significance(row.get('p_as_reported')) is True
                 and str(row.get('context', '')).startswith('Outside PI'))
        if not valid:
            withheld += 1
            continue
        key = (row.get('standard_roi_name'), row.get('hemisphere'), row.get('metric'))
        eligible.setdefault(key, []).append(row)
    matches, opposite = [], []
    for rows in eligible.values():
        if len(rows) != 1:
            withheld += len(rows)
            continue
        row = rows[0]
        same = (row['normative_status'] == 'below_95pi') == (float(row['pd_minus_control_cohen_d']) < 0)
        (matches if same else opposite).append(row)
    pd = dict(status='PD-like directional features' if matches else 'No eligible PD-like directional feature',
              pattern_present=bool(matches), doi=PD_DOI, reasons=matches, opposing_features=opposite,
              excluded_or_nonqualifying_rows=withheld,
              rule='Compatible whole-sample ENIGMA feature, outside the Potvin 95% PI, same effect direction, nominal source p<0.05; no diagnostic threshold.',
              significance='Nominal source p only; corrected significance is not established here.')
    pd['directional_profile'] = directional_profile
    if ad_candidate and matches:
        conclusion = 'AD-like regional pattern and PD-like directional features are both present. AD remains a candidate for further evaluation; MRI comparisons do not distinguish AD from PD or other causes.'
    elif ad_candidate:
        conclusion = 'AD-like regional pattern: AD remains a candidate for further evaluation based on the literature-linked measurements below. This does not establish AD or exclude PD and other causes.'
    elif matches:
        conclusion = 'PD-like directional features are present relative to ENIGMA PD group effects. This is descriptive literature concordance, not sufficient evidence to assign PD or exclude AD and other causes.'
    else:
        conclusion = 'Available literature-linked measurements do not support either summary pattern under the stated rules. Disease remains indeterminate; this does not establish Control or exclude AD or PD.'
        if scope == 'PD':
            conclusion = 'No eligible PD-like directional feature in the selected PD references. AD comparison was not run in PD-only scope. Disease remains indeterminate; this does not establish Control or exclude AD or PD.'
    if directional_profile['assessed'] and not matches:
        conclusion = (conclusion.replace('No eligible PD-like directional feature', 'No out-of-range PD-concordant feature')
                      + ' Normal-range directional concordance is reported separately below; it is not a PD classification.')
    return dict(schema_version=2, reference_focus=scope, conclusion=conclusion, ad=ad, pd=pd,
                assigned_diagnosis=None, disease_probabilities=None, known_diagnosis_used_as_input=False)


def from_result(result, subject_id):
    from reference_focus import pd_only
    from comparison_atlas import comparison_features
    from zheng_exploratory import compare
    from pd_evidence import compare_result
    root = Path(result.get('project_dir', Path(__file__).parent))
    path = root / 'workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json'
    scope = 'PD' if pd_only(result) else 'all'
    comparison = (compare(comparison_features(result).to_dict('records'),
                          json.loads(path.read_text()), subject_id)
                  if scope != 'PD' and path.exists() else None)
    return summarize(comparison, compare_result(result, subject_id), scope)


def number(value):
    return f'{float(value):.3f}'.rstrip('0').rstrip('.') if finite(value) else 'Not available'


def render(summary, *, compact=False, intro=True):
    if compact:
        return render_compact(summary)
    esc = lambda value: html.escape(str(value), quote=True)
    out = ['<section class="possible-disease-interpretation">']
    if intro:
        out += ['<h4>Possible Disease Interpretation</h4>',
                '<p><b>' + esc(summary['conclusion']) + '</b></p>',
                '<p>Research interpretation, conditional on segmentation QC. Neither pattern is a clinical diagnosis, a disease probability, or an independent validation result.</p>']
    out += ['<h5>AD-like: literature-linked reasons</h5><p>' + esc(summary['ad']['status']) + '.</p>']
    if summary['reference_focus'] != 'PD':
        out.append('<p>Source: <a href="https://doi.org/' + AD_DOI + '">Zheng et al. (2023)</a>, S1 AD / S2 Control. '
                   'Reference means and SDs are recomputed from the supplements. The four-region rule below is this workflow\'s exploratory rule, not a reproduction of the paper\'s validated classifier.</p>')
    for warning in summary['ad']['warnings']:
        out.append('<p role="alert">' + esc(warning) + '</p>')
    if summary['reference_focus'] != 'PD':
        out.append('<p>Rule: ' + esc(summary['ad']['rule']) + '</p>')
    ad_rows = summary['ad']['reasons']
    if ad_rows:
        out.append('<div style="overflow:auto"><table><tr><th>ROI / side</th><th>Measured</th><th>AD mean +/- SD</th><th>Control mean +/- SD</th><th>Log-density ratio AD/Control</th><th>Reason</th></tr>')
        for row in ad_rows:
            relation = ('Higher AD marginal density' if row['closer_density'] == 'AD' else
                        'Higher Control marginal density' if row['closer_density'] == 'Control' else 'Equal marginal density')
            if row.get('atypical_both'):
                relation += '; atypical under both references (interpret cautiously)'
            cells = (row['roi'] + ' / ' + row['hemisphere'], number(row['observed']) + ' ' + row['unit'],
                     number(row['AD_mean']) + ' +/- ' + number(row['AD_sd']),
                     number(row['Control_mean']) + ' +/- ' + number(row['Control_sd']),
                     number(row['log_density_ratio_AD_Control']), relation)
            out.append('<tr>' + ''.join('<td>' + esc(cell) + '</td>' for cell in cells) + '</tr>')
        out.append('</table></div>')
    else:
        out.append('<p>No eligible AD regional comparison in this report; missing data are not evidence against AD.</p>')
    out += ['<h5>PD-like: ENIGMA literature-linked reasons</h5><p>' + esc(summary['pd']['status']) + '.</p>',
            '<p>Source: <a href="https://doi.org/' + PD_DOI + '">Laansma et al. (2021), ENIGMA PD</a>. '
            'Potvin supplies the patient normative PI; ENIGMA supplies the published PD-minus-Control direction, not an individual PD range.</p>',
            '<p>Rule: ' + esc(summary['pd']['rule']) + '</p>']
    if summary['pd'].get('directional_profile'):
        from pd_pattern_profile import render as render_profile
        out.append(render_profile(summary['pd']['directional_profile']))
    for label, rows in (('Matching features', summary['pd']['reasons']),
                        ('Opposite-direction features (retained, not counted as support)', summary['pd']['opposing_features'])):
        if not rows:
            continue
        out.append('<h6>' + esc(label) + '</h6><div style="overflow:auto"><table><tr><th>ROI / side</th><th>Metric / measured</th><th>Patient vs Potvin PI</th><th>ENIGMA PD-Control d</th><th>Source p (nominal)</th><th>Source location</th></tr>')
        for row in rows:
            cells = (str(row.get('standard_roi_name')) + ' / ' + str(row['hemisphere']),
                     row['metric'] + ' / ' + number(row['measured']) + ' ' + row['unit'],
                     row['normative_status'], number(row['pd_minus_control_cohen_d']),
                     row['p_as_reported'], str(row.get('source_table', '')) + ', page ' + str(row.get('source_page', '')))
            out.append('<tr>' + ''.join('<td>' + esc(cell) + '</td>' for cell in cells) + '</tr>')
        out.append('</table></div>')
    out.append('<p>' + esc(summary['pd']['significance']) + ' Nonsignificant, incompatible, source-conflicting and QC-held measurements cannot trigger PD-like. HY-stage comparisons are not counted as independent evidence. PPMI overlap with ENIGMA is unresolved; no HY stage is assigned.</p></section>')
    return ''.join(out)


def _region_list(rows, key):
    regions = [str(row[key]) + ' / ' + str(row['hemisphere']) for row in rows]
    text = '; '.join(regions[:5])
    return text + (f'; {len(regions) - 5} more in the evidence details' if len(regions) > 5 else '')


def render_compact(summary):
    esc = lambda value: html.escape(str(value), quote=True)
    ad, pd = summary['ad'], summary['pd']
    out = ['<section class="possible-disease-interpretation" data-summary-layout="merged">',
           '<p><b>Possible disease interpretation:</b> ' + esc(summary['conclusion']) + '</p>']
    if summary['reference_focus'] == 'PD':
        ad_reason = 'Not assessed in PD-only scope; no AD conclusion is drawn.'
    elif ad['reasons']:
        favoring = [row for row in ad['reasons'] if row.get('closer_density') == 'AD']
        if ad['candidate']:
            ad_reason = ('Four-region rule met: higher AD-reference density in ' +
                         _region_list(favoring, 'roi') + '.')
        else:
            ad_reason = (f"Four-region rule not met: {len(favoring)}/{len(ad['reasons'])} "
                         'available hippocampal/amygdala volumes favor the AD reference.')
        ad_reason = esc(ad_reason) + ' Exploratory reference: <a href="https://doi.org/' + AD_DOI + '">Zheng et al. (2023), S1/S2</a>.'
    else:
        ad_reason = 'No eligible AD regional comparison; missing data do not exclude AD.'
    out.append('<p><b>AD-like:</b> ' + ad_reason + '</p>')
    if pd['reasons']:
        pd_reason = ('Out-of-range measurements follow the ENIGMA PD group-effect direction in ' +
                     _region_list(pd['reasons'], 'standard_roi_name') + '.')
    else:
        pd_reason = 'No eligible directional match outside the normative PI; this does not exclude PD.'
    if pd.get('directional_profile', {}).get('assessed'):
        from pd_pattern_profile import description
        pd_reason += ' ' + description(pd['directional_profile'])
    if pd['opposing_features']:
        pd_reason += f" {len(pd['opposing_features'])} opposite-direction features are retained, not counted as support."
    out.append('<p><b>PD-like:</b> ' + esc(pd_reason) +
               ' <a href="https://doi.org/' + PD_DOI + '">Laansma et al. (2021), ENIGMA PD</a>. '
               'Nominal group-level associations, not a patient diagnosis.</p>')
    if any(str(warning).startswith('Age applicability warning:') for warning in ad['warnings']):
        out.append('<p class="note">Age outside the reference cohort: comparisons are extrapolative; age alone does not exclude AD.</p>')
    out.append('<p class="note">Interpretation is conditional on segmentation QC and unresolved method compatibility; no calibrated disease probability is available.</p>')
    evidence = render(summary, intro=False)
    evidence = evidence.removeprefix('<section class="possible-disease-interpretation">').removesuffix('</section>')
    out.append('<details><summary>Interpretation evidence and rules</summary>' + evidence + '</details></section>')
    return ''.join(out)


def merge_summary_html(content, summary):
    previous = INTERPRETATION_SECTION.sub('', content)
    if previous.count('<h4>Demographic</h4>') != 1 or previous.count('<h4>Summary</h4>') != 1:
        raise ValueError('Expected one Demographic and one Summary section')
    match = re.search(r'<h4>Summary</h4>\s*<p>.*?</p>', previous, re.S)
    if match is None or previous.index('<h4>Demographic</h4>') > match.start():
        raise ValueError('Expected numerical Summary after Demographic')
    updated = previous[:match.end()] + render(summary, compact=True) + previous[match.end():]
    assert INTERPRETATION_SECTION.sub('', updated) == previous
    return updated
