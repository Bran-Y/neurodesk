"""Label-blind, uncalibrated per-feature AD/Control comparison. No posterior."""
import csv
import html
import json
import math
from collections import defaultdict
from pathlib import Path
from comparison_atlas import feature_key, translate_records, mapping_error


LIMITS = ('User-authorized exploratory use; approval does not establish measurement calibration. '
          'Pooled ages, unadjusted volumes, unknown reference software release and '
          'unresolved printed/supplement discrepancies. Gaussian marginal assumptions '
          'are unvalidated; correlated features are not multiplied into a likelihood '
          'or converted into disease probabilities. Only AD versus Control is tested.')


def compare(features, references, subject_id):
    registry = next((r.get('comparison_registry') for r in features if r.get('comparison_registry')), None)
    features = translate_records(features, registry)
    references = translate_records(references, registry)
    patient = [r for r in features if r['subject_id'] == subject_id]
    if not patient:
        raise ValueError('Subject absent: ' + subject_id)
    indexed = defaultdict(list)
    for ref in references:
        if ref.get('doi') == '10.1371/journal.pone.0279574':
            indexed[feature_key(ref)].append(ref)
    rows, excluded, warnings = [], [], set()
    seen = set()
    for p in patient:
        k = feature_key(p)
        if k in seen:
            raise ValueError('Duplicate patient feature: ' + str(k))
        seen.add(k)
        refs = indexed.get(k, [])
        try:
            if mapping_error(p):
                raise ValueError(mapping_error(p))
            groups = {g: [r for r in refs if r['diagnosis'] == g] for g in ('AD', 'Control')}
            if any(len(v) != 1 for v in groups.values()):
                raise ValueError('Missing or duplicate AD/Control reference')
            pair = {g: v[0] for g, v in groups.items()}
            x, age = float(p['value_numeric']), float(p['age'])
            if not math.isfinite(x) or not math.isfinite(age):
                raise ValueError('Nonfinite patient value/age')
            if p.get('statistic_type') != 'raw_measure':
                raise ValueError('Patient normalization incompatible')
            scores, record = {}, dict(roi=k[0], hemisphere=k[1], metric=k[2], observed=x, unit=p['unit'], age_applicable=True)
            for g, r in pair.items():
                if mapping_error(r):
                    raise ValueError(mapping_error(r))
                if r.get('human_review_status') != 'accepted':
                    raise ValueError('Reference not approved')
                if p['comparison_atlas_code'] != r['comparison_atlas_code'] or not p.get('unit') or p.get('unit') != r.get('unit'):
                    raise ValueError('Atlas or unit incompatible')
                if any(v.get('atlas_translation_review_status') != 'reviewed_quantitative_ready' for v in (p, r)):
                    warnings.add('Research comparison authorised; no repeat approval is required for these accepted references. '
                                 'Results are exploratory because atlas and processing-method compatibility has not been fully validated.')
                if not float(r['reference_age_min']) <= age <= float(r['reference_age_max']):
                    record['age_applicable'] = False
                    warnings.add('Age applicability warning: participant age is outside the reference cohort range. '
                                 'Assessment continues using the available paired measurements, but comparisons are extrapolative; '
                                 'young age does not exclude AD or establish Control.')
                mu, sd = float(r['mean']), float(r['standard_deviation'])
                if not all(map(math.isfinite, (mu, sd))) or sd <= 0 or r['sample_size'] < 2:
                    raise ValueError('Invalid distribution')
                z = (x - mu) / sd
                scores[g] = -math.log(sd) - z*z/2
                record.update({g+'_mean': mu, g+'_sd': sd, g+'_z': z})
            delta = scores['AD'] - scores['Control']
            record.update(log_density_ratio_AD_Control=delta,
                          source_roi_name=p.get('source_roi_name'),
                          standard_roi_name=p.get('standard_roi_name'),
                          atlas_translation_review_status=p.get('atlas_translation_review_status'),
                          comparison_registry=p.get('comparison_registry'),
                          closer_density='AD' if delta > 1e-12 else 'Control' if delta < -1e-12 else 'Tie',
                          atypical_both=abs(record['AD_z']) > 1.96 and abs(record['Control_z']) > 1.96,
                          doi=pair['AD']['doi'], source='S1 AD / S2 Control')
            rows.append(record)
        except (ValueError, TypeError, KeyError) as err:
            excluded.append(dict(feature=' | '.join(k), reason=str(err)))
    families = []
    for metric in sorted({r['metric'] for r in rows}):
        subset = [r for r in rows if r['metric'] == metric]
        families.append(dict(metric=metric, n=len(subset),
                             AD=sum(r['closer_density'] == 'AD' for r in subset),
                             Control=sum(r['closer_density'] == 'Control' for r in subset),
                             atypical_both=sum(r['atypical_both'] for r in subset)))
    return dict(subject_id=subject_id, use='user_authorized_exploratory', limitations=LIMITS,
                comparison_role='reference_cohort_marginal_density_not_patient_class',
                disease_prediction=None, families=families, features=rows, exclusions=excluded,
                warnings=sorted(warnings))


def regional_candidate(result):
    """A label-blind regional hypothesis, never an AD/PD/Control classifier."""
    required = {(roi, side) for roi in ('hippocampus', 'amygdala') for side in ('lh', 'rh')}
    rows = [r for r in result['features'] if r['roi'] in ('hippocampus', 'amygdala')
            and r['metric'] == 'roi_volume']
    matched = len(rows) == 4 and {(r['roi'], r['hemisphere']) for r in rows} == required
    return matched and all(r['closer_density'] == 'AD' and
                           math.isfinite(float(r['observed'])) and float(r['observed']) > 0
                           for r in rows)


def render(result):
    esc = html.escape
    out = ['<h4>Exploratory Zheng AD / Control comparison: '+esc(result['subject_id'])+'</h4>']
    for warning in result.get('warnings', []):
        out.append('<p role="alert"><b>' + esc(warning) + '</b></p>')
    highlights = [r for r in result['features'] if r['roi'] in ('hippocampus', 'amygdala') and r['metric']=='roi_volume']
    out.append(f"<p>Evaluated paired measurements: {len(result['features'])}. "
               "Age outside the reference cohort does not suppress this exploratory assessment.</p>")
    if regional_candidate(result):
        out.append('<p><b>AD-like regional pattern; AD remains a candidate for further evaluation.</b> All four bilateral hippocampal '
                   'and amygdala volumes have higher density under the AD distributions. Other features '
                   'may favor Control; this is an exploratory candidate interpretation, not a diagnosis, '
                   'a validated prediction, or evidence that AD is the most likely disease. '
                   'Rule: both hippocampi and both amygdalae must have higher AD marginal density; '
                   'other ROI counts cannot trigger this candidate. PD and other causes have not '
                   'been discriminated by this two-reference comparison.</p>')
    elif result['features']:
        out.append('<p>Exploratory AD/Control feature comparisons are available below. '
                   'No validated disease classification is assigned.</p>')
    out.append('<table><tr><th>Measurements</th><th>Compared</th><th>Higher density: AD reference</th><th>Higher density: Control reference</th></tr>')
    if highlights:
        out.append(f"<tr><td>Bilateral hippocampal/amygdala volumes (subset of volumes below)</td><td>{len(highlights)}</td><td>{sum(r['closer_density']=='AD' for r in highlights)}</td><td>{sum(r['closer_density']=='Control' for r in highlights)}</td></tr>")
    for f in result['families']:
        out.append(f"<tr><td>{esc(f['metric'])}</td><td>{f['n']}</td><td>{f['AD']}</td><td>{f['Control']}</td></tr>")
    out.append('</table><p>Counts are descriptive, not independent votes or diagnostic support grades.</p>')
    if not result['features']:
        out.append('<p><b>No applicable paired features; agreement is unavailable, not 0%.</b> This does not exclude AD or establish Control.</p>')
    reasons = sorted({r['reason'] for r in result['exclusions']})
    out.append('<p>Exclusion reasons: '+esc('; '.join(reasons) or 'None')+'</p>')
    out.append('<p>'+esc(LIMITS)+'</p>')
    out.append('<p>No calibrated disease prediction. Positive log-density ratio favors the AD marginal '
               'distribution; negative favors Control. Atypical-both is a Gaussian tail flag, not a validated interval.</p>')
    fields = ['roi', 'hemisphere', 'metric', 'observed', 'unit', 'AD_mean', 'AD_sd', 'Control_mean',
              'Control_sd', 'AD_z', 'Control_z', 'log_density_ratio_AD_Control', 'closer_density', 'atypical_both', 'age_applicable']
    out.append('<details><summary>Per-feature reference-density comparisons (not patient diagnoses)</summary><table><tr>')
    out.extend('<th>'+esc(k)+'</th>' for k in fields)
    out.append('</tr>')
    for r in result['features']:
        out.append('<tr>'+''.join('<td>'+esc(f'{r[k]:.3f}' if isinstance(r[k], float) else str(r[k]))+'</td>' for k in fields)+'</tr>')
    out.append('</table></details><details><summary>Excluded features</summary><pre>'+esc(json.dumps(result['exclusions'], indent=2))+'</pre></details>')
    out.append('<p>Source: <a href="https://doi.org/10.1371/journal.pone.0279574">Zheng et al. (2023), '
               'Computer assisted diagnosis of Alzheimer\'s disease using statistical likelihood-ratio test</a>. '
               'S1 AD / S2 Control, 263 scan records per group; means and SDs recomputed from supplements. '
               'Registry: workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json. '
               '<b>For research reference only; not a substitute for clinical diagnosis.</b></p>')
    return ''.join(out)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root
    refs = json.loads((root/'workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json').read_text())
    with (root/'finished_workflow_outputs/subject_features_with_covariates.csv').open() as f:
        features = list(csv.DictReader(f))
    result = compare(features, refs, 'OAS1_0003_MR1')
    target = root/'finished_workflow_outputs/zheng_exploratory'
    target.mkdir(parents=True, exist_ok=True)
    (target/'OAS1_0003_MR1.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    (target/'OAS1_0003_MR1.html').write_text('<!doctype html><meta charset="utf-8">'+render(result))
    print(json.dumps(result['families'], indent=2))
    print(json.dumps([r for r in result['features'] if r['roi'] in ('hippocampus','amygdala')], indent=2))
