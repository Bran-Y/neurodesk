"""Label-blind, descriptive ENIGMA directional concordance, not classification."""
import html
import math

DOI = '10.1002/mds.28706'


def finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def profile(rows):
    from pd_evidence import nominal_significance
    groups = {}
    excluded = 0
    for row in rows:
        valid = (row.get('doi') == DOI and row.get('comparison_group') == 'whole_sample'
                 and row.get('match_status') == 'matched_for_context'
                 and row.get('direction_eligible') is True
                 and row.get('review_status') != 'rejected'
                 and row.get('mapping_method') == 'same_native_atlas_label_alignment'
                 and row.get('normative_status') in ('within_95pi', 'below_95pi', 'above_95pi')
                 and all(finite(row.get(k)) for k in ('measured', 'expected_value', 'pd_minus_control_cohen_d'))
                 and float(row['measured']) > 0 and float(row['expected_value']) > 0
                 and float(row['pd_minus_control_cohen_d']) != 0
                 and nominal_significance(row.get('p_as_reported')) is True)
        key = (row.get('standard_roi_name'), row.get('hemisphere'), row.get('metric'))
        if not valid or not all(key):
            excluded += 1
            continue
        groups.setdefault(key, []).append(row)
    aligned, opposed, equal = [], [], []
    for group in groups.values():
        if len(group) != 1:
            excluded += len(group)
            continue
        row = dict(group[0])
        delta = float(row['measured']) - float(row['expected_value'])
        row['deviation_from_expected'] = delta
        if math.isclose(float(row['measured']), float(row['expected_value']), rel_tol=1e-9, abs_tol=1e-9):
            relation, target = 'at_expected', equal
        elif (delta < 0) == (float(row['pd_minus_control_cohen_d']) < 0):
            relation, target = 'same_direction', aligned
        else:
            relation, target = 'opposite_direction', opposed
        row['direction_relation'] = relation
        target.append(row)
    key = lambda r: (str(r['standard_roi_name']), str(r['hemisphere']), str(r['metric']))
    return dict(assessed=len(aligned) + len(opposed) + len(equal),
                aligned=sorted(aligned, key=key), opposed=sorted(opposed, key=key),
                at_expected=sorted(equal, key=key), excluded=excluded,
                classification_threshold=None, disease_probability=None,
                rule='Sign of measured minus Potvin expected mean versus ENIGMA whole-sample PD-Control d; nominal source p<0.05. Includes measurements within the PI.',
                limitation='Descriptive cross-reference concordance only: Potvin and ENIGMA are different cohorts. ROI signs are correlated, not independent votes. No validated PD/Control cutoff; normal-range concordance is not abnormality or diagnostic evidence.')


def description(data):
    if not data['assessed']:
        return 'PD-pattern comparison not assessable: no eligible measurements with normative expected means.'
    within = sum(r['normative_status'] == 'within_95pi' for r in data['aligned'])
    return (f"PD-pattern directional concordance: {len(data['aligned'])}/{data['assessed']} measurements "
            f"follow the ENIGMA PD direction ({within} within the normative PI); "
            f"{len(data['opposed'])} opposite, {len(data['at_expected'])} at the expected mean. "
            'This is a descriptive profile, not a positive PD classification.')


def render(data):
    esc = lambda v: html.escape(str(v), quote=True)
    out = ['<div class="pd-pattern-profile"><p>' + esc(description(data)) + '</p>',
           '<details><summary>PD-pattern concordance: measurements and opposing findings</summary>',
           '<p>' + esc(data['rule']) + '</p><p>' + esc(data['limitation']) + '</p>',
           '<div style="overflow:auto;max-height:480px"><table><tr><th>ROI / side</th><th>Metric</th>',
           '<th>Measured</th><th>Potvin expected</th><th>Normative status</th><th>ENIGMA d</th>',
           '<th>Source p (nominal)</th><th>Relation</th></tr>']
    for row in data['aligned'] + data['opposed'] + data['at_expected']:
        values = (str(row['standard_roi_name']) + ' / ' + str(row['hemisphere']), row['metric'],
                  f"{float(row['measured']):.3f} {row.get('unit', '')}", f"{float(row['expected_value']):.3f}",
                  row['normative_status'], row['pd_minus_control_cohen_d'], row['p_as_reported'], row['direction_relation'])
        out.append('<tr>' + ''.join('<td>' + esc(v) + '</td>' for v in values) + '</tr>')
    out.append('</table></div></details></div>')
    return ''.join(out)
