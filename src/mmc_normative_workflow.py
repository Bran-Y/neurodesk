"""Describe individual morphology using the supplied DK calculator and literature."""
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd


def _regularized_incomplete_beta(x, a, b):
    """Evaluate I_x(a,b) with the standard continued-fraction algorithm."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0

    def fraction(aa, bb, xx):
        qab, qap, qam = aa + bb, aa + 1.0, aa - 1.0
        c = 1.0
        d = 1.0 - qab * xx / qap
        d = 1.0 / max(abs(d), 1e-300) * (1 if d >= 0 else -1)
        value = d
        for step in range(1, 201):
            even = step * (bb - step) * xx / ((qam + 2 * step) * (aa + 2 * step))
            d = 1.0 + even * d
            d = 1.0 / max(abs(d), 1e-300) * (1 if d >= 0 else -1)
            c = 1.0 + even / c
            c = max(abs(c), 1e-300) * (1 if c >= 0 else -1)
            value *= d * c
            odd = -(aa + step) * (qab + step) * xx / ((aa + 2 * step) * (qap + 2 * step))
            d = 1.0 + odd * d
            d = 1.0 / max(abs(d), 1e-300) * (1 if d >= 0 else -1)
            c = 1.0 + odd / c
            c = max(abs(c), 1e-300) * (1 if c >= 0 else -1)
            delta = d * c
            value *= delta
            if abs(delta - 1.0) < 3e-14:
                break
        return value

    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * fraction(a, b, x) / a
    return 1.0 - front * fraction(b, a, 1.0 - x) / b


def _student_t_cdf(value, degrees_of_freedom):
    if degrees_of_freedom <= 0:
        raise ValueError('Student t degrees of freedom must be positive')
    if value == 0:
        return 0.5
    beta = _regularized_incomplete_beta(
        degrees_of_freedom / (degrees_of_freedom + value * value),
        degrees_of_freedom / 2.0,
        0.5,
    )
    return 1.0 - beta / 2.0 if value > 0 else beta / 2.0


def load_models(path):
    return json.loads(Path(path).read_text())


def classify_prediction_interval(observed, lower, upper):
    """Classify unrounded measurements; both prediction bounds are inclusive."""
    if not all(np.isfinite(float(v)) for v in (observed, lower, upper)):
        raise ValueError('Non-finite prediction interval input')
    if lower > upper:
        raise ValueError('Reversed prediction interval bounds')
    if observed < lower:
        return 'below_95pi'
    if observed > upper:
        return 'above_95pi'
    return 'within_95pi'


def predict(model, pack, age, sex, etiv, strength, manufacturer, observed):
    """Port the workbook's C/D/E/F/I/L formulas, including its 1.961 multiplier."""
    vals = [age, etiv, strength, observed]
    if not all(np.isfinite(float(v)) for v in vals) or etiv <= 0 or observed <= 0:
        raise ValueError('Non-finite or non-positive measurement/covariate')
    if not pack['age_range'][0] <= age <= pack['age_range'][1]:
        raise ValueError('Age outside model range')
    sex_code = {'male': 1, 'female': 0}.get(str(sex).lower())
    if sex_code is None or strength not in (1.5, 3.0):
        raise ValueError('Unsupported sex or scanner field strength')
    manufacturer = manufacturer.lower()
    if manufacturer not in ('ge', 'philips', 'siemens'):
        raise ValueError('Unsupported scanner manufacturer')
    a, v, s = age - pack['age_center'], etiv - pack['etiv_center'], int(strength == 1.5)
    ge, philips = int(manufacturer == 'ge'), int(manufacturer == 'philips')
    terms = dict(b0=1, agec=a, agec2=a*a, agec3=a*a*a, sexq=sex_code,
                 tivc=v, tivc2=v*v, tivc3=v*v*v, mfsq=s, ge=ge, philips=philips,
                 ge_x_mfsq=ge*s, philips_x_mfsq=philips*s,
                 tivc_x_mfsq=v*s, agec_x_sexq=a*sex_code,
                 tivc_x_ge=v*ge, tivc_x_philips=v*philips)
    x = np.array([terms[n.lower()] for n in model['terms']])
    expected = float(x @ np.array(model['beta']))
    leverage = float(x @ np.array(model['covariance']) @ x)
    mse = float(model['mse'])
    if mse <= 0 or leverage < -1e-8:
        raise ValueError('Invalid model variance')
    se = float(np.sqrt(mse * (1 + max(0, leverage))))
    lower, upper = expected - pack['interval_multiplier']*se, expected + pack['interval_multiplier']*se
    return dict(expected_value=expected, lower_95pi=lower, upper_95pi=upper,
                zop=(observed-expected)/np.sqrt(mse),
                percentile=100*_student_t_cdf((observed-expected)/se, pack['percentile_df']),
                expected_direction='below_expected' if observed < expected else 'above_expected' if observed > expected else 'at_expected',
                range_status=classify_prediction_interval(observed, lower, upper),
                calculation_status='calculated', prediction_se=se)


def enrich_covariates(features, fs_root, dataset_root):
    """Use subject-specific FreeSurfer eTIV; restrict dataset scanner facts to OAS1."""
    data = features.copy()
    for sid, patient in data.groupby('subject_id'):
        stats = Path(fs_root) / sid / 'stats' / 'aseg.stats'
        etiv = None
        if stats.exists():
            for line in stats.read_text().splitlines():
                if line.startswith('# Measure EstimatedTotalIntraCranialVol,'):
                    etiv = float(line.split(',')[3])
        mask = data.subject_id.eq(sid)
        if etiv is not None:
            data.loc[mask, 'estimated_total_intracranial_volume'] = etiv
            data.loc[mask, 'etiv_source'] = str(stats) + ': EstimatedTotalIntraCranialVol (mm3)'
        xml = Path(dataset_root) / sid / (sid + '.xml')
        if re.fullmatch(r'OAS1_\d{4}_MR\d', str(sid)) and xml.exists():
            # Dataset-level acquisition facts, explicitly distinct from individual DICOM metadata.
            data.loc[mask, 'scanner_field_strength'] = 1.5
            data.loc[mask, 'scanner_manufacturer'] = 'Siemens'
            data.loc[mask, 'scanner_source'] = 'OASIS-1 acquisition protocol; 10.1162/jocn.2007.19.9.1498; dataset-level assignment'
    return data


def evaluate_features(features, pack):
    from comparison_atlas import prepare_features, translate_records, feature_key, mapping_error
    if 'comparison_registry' not in features:
        features = prepare_features(features)
    registry = features.iloc[0]['comparison_registry'] if len(features) else None
    models = translate_records([dict(m, atlas_name='Desikan-Killiany') for m in pack['models']], registry)
    index = {feature_key(m): m for m in models if not mapping_error(m)}
    records = []
    key_cols = ['subject_id', 'roi_name', 'hemisphere', 'imaging_metric']
    duplicates = pd.Series([(r['subject_id'], *feature_key(r)) for r in features.to_dict('records')]).duplicated(keep=False)
    for pos, (_, row) in enumerate(features.iterrows()):
        rec = {k: row.get(k) for k in key_cols + ['age', 'sex', 'unit', 'atlas_name', 'source_file',
                'estimated_total_intracranial_volume', 'scanner_field_strength', 'scanner_manufacturer', 'etiv_source', 'scanner_source']}
        rec.update(observed_value=row.get('value_numeric'), calculation_status='not_calculated',
                   source_title=pack['source_title'], source_doi=pack['doi'], source_sha256=pack['source_sha256'],
                   method_note='Reference FreeSurfer 5.3; measurement version: ' + str(row.get('processing_software_version', row.get('atlas_version', 'unknown'))) + '. Segmentation QC and method compatibility require review. Pointwise 95% PI; no multiple-comparison correction.',
                   processing_software_version=row.get('processing_software_version', row.get('atlas_version', 'unknown')),
                   normative_review_status='pending_human_review')
        rec.update(standard_roi_name=row.get('standard_roi_name'),
                   standard_hemisphere=row.get('standard_hemisphere'),
                   atlas_translation_review_status=row.get('atlas_translation_review_status'))
        model = index.get(feature_key(row))
        try:
            if mapping_error(row):
                raise ValueError(mapping_error(row))
            if duplicates.iloc[pos]:
                raise ValueError('Duplicate feature key: choose one processing run')
            if model is None:
                raise ValueError('No matching cortical DK model in mmc1 (aseg/subcortical not covered)')
            source_name = Path(str(row.get('source_file', ''))).name
            atlas = str(row.get('atlas_name', '')).lower()
            if source_name not in ('lh.aparc.stats', 'rh.aparc.stats') or 'dkt' in atlas or 'tourville' in atlas:
                raise ValueError('DK aparc source required; label translation does not harmonize atlases')
            if not source_name.startswith(str(row.hemisphere) + '.'):
                raise ValueError('Hemisphere disagrees with source file')
            from processing_compatibility import same_version
            if not same_version(row.get('processing_software_version'), pack.get('reference_freesurfer_version')):
                raise ValueError('Processing version missing or different from the cortical reference; cross-version calibration required')
            if str(row.get('source_pipeline', '')).strip().lower() != 'freesurfer':
                raise ValueError('FreeSurfer processing pipeline required; label identity is not method equivalence')
            if row.get('unit') != model['unit']:
                raise ValueError('Unit mismatch')
            for field in ['age', 'sex', 'estimated_total_intracranial_volume', 'scanner_field_strength', 'scanner_manufacturer']:
                if pd.isna(row.get(field)):
                    raise ValueError('Missing covariate: ' + field)
            rec.update(predict(model, pack, float(row.age), row.sex,
                               float(row.estimated_total_intracranial_volume),
                               float(row.scanner_field_strength), row.scanner_manufacturer,
                               float(row.value_numeric)))
            rec.update(model_id=model['model_id'], source_cells=model['source_cells'], exclusion_reason='')
        except (ValueError, TypeError) as exc:
            rec['exclusion_reason'] = str(exc)
        records.append(rec)
    return pd.DataFrame(records)


def qualitative_links(results, references):
    """Retrieve ROI candidates; preserve original claims, methods and review status."""
    from neurodesk_literature_to_pgsql import normalize_mmc_region_label
    rows = []
    for _, result in results.iterrows():
        if result.calculation_status != 'calculated':
            continue
        for ref in references:
            if normalize_mmc_region_label(ref.get('roi_name', '')) != normalize_mmc_region_label(result.roi_name):
                continue
            if ref.get('imaging_metric') != result.imaging_metric:
                continue
            hemi = ref.get('hemisphere')
            if hemi not in (result.hemisphere, 'bilateral', None, ''):
                continue
            claim = ref.get('evidence_note') or ref.get('pattern_summary')
            if not claim:
                continue
            rows.append(dict(subject_id=result.subject_id, roi_name=result.roi_name,
                             hemisphere=result.hemisphere, imaging_metric=result.imaging_metric,
                             range_status=result.range_status,
                             paper_id=ref.get('paper_id') or ref.get('paper_code') or ref.get('reference_id'),
                             paper_code=ref.get('paper_code'), evidence_id=ref.get('evidence_id'),
                             evidence_kind=ref.get('evidence_kind'),
                             registry_locations=ref.get('registry_locations'),
                             source_url=ref.get('source_url'),
                             source_original=ref.get('source_original'),
                             extraction_method=ref.get('extraction_method'),
                             extraction_status=ref.get('extraction_status'),
                             source_check_status=ref.get('source_check_status'),
                             source_title=ref.get('source_title'), doi=ref.get('doi'),
                             source_location=ref.get('source_location') or ref.get('table_or_figure'), literature_statement=claim,
                             literature_atlas=ref.get('atlas_name'),
                             literature_method=ref.get('processing_pipeline'),
                             literature_hemisphere=hemi,
                             source_review_status=ref.get('manual_review_status', 'unrecorded'),
                             matching_rule='same ROI and metric; same or bilateral/unspecified hemisphere; qualitative candidate only',
                             numeric_use=False, case_review_status='pending_human_review',
                             interpretation='Context for the measured ROI. Anatomical correspondence and applicability of the paper finding need case review. No disease or behavior is inferred from this match.'))
    return pd.DataFrame(rows).drop_duplicates() if rows else pd.DataFrame()


def build_report(results, links, subject_id):
    case = results[results.subject_id.eq(subject_id)]
    if case.empty:
        return f'No measurements for {subject_id}'
    first = case.iloc[0]
    valid = case[case.calculation_status.eq('calculated')]
    abnormal = valid[valid.range_status.isin(['below_95pi', 'above_95pi'])] if len(valid) else valid
    lines = [f'# Brain morphology and literature report: {subject_id}',
             f'Age: {first.age}; sex: {first.sex}.',
             '## Normative summary',
             f'{len(valid)} measurements compared with applicable Potvin models; {len(abnormal)} outside the pointwise 95% prediction interval.',
             'These measurements describe current morphology. A cross-sectional low value does not establish progressive atrophy, a disease, or an individual behavioral deficit.',
             'The 95% intervals are pointwise and uncorrected across ROIs. Review segmentation quality and software-version effects before accepting a finding.',
             '## Measurements relative to expected values']
    statuses = ['below_95pi', 'within_95pi', 'above_95pi']
    if len(valid):
        checked = valid.apply(lambda r: classify_prediction_interval(r.observed_value, r.lower_95pi, r.upper_95pi), axis=1)
        if not checked.eq(valid.range_status).all():
            raise ValueError('Report range classification differs from prediction bounds')
    counts = valid.range_status.value_counts().reindex(statuses, fill_value=0)
    explanation = [
        '## Range classification and counting unit',
        'The counting unit is one feature row per subject: ROI x hemisphere x imaging metric. '
        'Left/right hemispheres and volume/cortical thickness are separate rows; counts are not unique brain regions.',
        'below_95pi: observed < lower bound; within_95pi: lower bound <= observed <= upper bound; '
        'above_95pi: observed > upper bound. Both boundaries are included in within_95pi.',
        'Classification uses unrounded values; tables round values for display only. '
        'expected_direction describes position relative to the predicted mean and is not the normal-range classification. '
        'A below_expected measurement can still be within_95pi.',
        counts.rename_axis('range_status').reset_index(name='feature_rows').to_markdown(index=False),
        f'Total input feature rows: {len(case)}; calculated: {len(valid)}; not calculated: {len(case) - len(valid)}. '
        'Uncalculated rows are unassessed and are excluded from the three range categories.',
    ]
    lines[-1:-1] = explanation
    if len(valid):
        cols = ['roi_name', 'hemisphere', 'imaging_metric', 'observed_value', 'unit', 'expected_value',
                'lower_95pi', 'upper_95pi', 'zop', 'percentile', 'expected_direction', 'range_status']
        lines.append(valid[cols].round(4).to_markdown(index=False))
    else:
        lines.append('Normal reference values could not be calculated; see missing inputs below.')
    excluded = case[case.calculation_status.ne('calculated')]
    if len(excluded):
        lines += ['## Coverage gaps', excluded.exclusion_reason.value_counts().rename_axis('reason').reset_index(name='rows').to_markdown(index=False)]
    lines += ['## Literature context']
    case_links = links[links.subject_id.eq(subject_id)] if len(links) else links
    if len(case_links):
        lines += ['The following are source-linked candidates for qualitative interpretation. They remain pending case review, including whether a bilateral paper ROI corresponds to the measured hemisphere.',
                  case_links[['roi_name', 'hemisphere', 'range_status', 'paper_id', 'literature_statement', 'source_location', 'case_review_status']].to_markdown(index=False)]
    else:
        lines += ['No matching source statements are available for these measurements. No behavioral association has been invented.']
    lines += ['## References and provenance']
    for _, source in valid[['source_title', 'source_doi', 'source_sha256']].drop_duplicates().iterrows():
        lines.append(f'MMC normative model: [{source.source_title}](https://doi.org/{source.source_doi}). Workbook SHA256: {source.source_sha256}')
    lines += ['Cortical models: mmc1 Desikan-Killiany. Four eligible native aseg volumes: mmc2 bilateral hippocampus/amygdala, Calc formula concordance checked; not native Excel or clinical validation.',
              'Reference FreeSurfer 5.3. Measurement software version: ' + str(first.get('processing_software_version', 'unknown')) + '. Matching versions do not replace segmentation QC or method validation.',
              str(first.get('etiv_source', 'eTIV source unavailable')),
              str(first.get('scanner_source', 'scanner source unavailable'))]
    if len(case_links):
        for _, ref in case_links[['paper_id', 'source_title', 'doi']].drop_duplicates().iterrows():
            lines.append(f'- {ref.paper_id}: {ref.source_title}. DOI: {ref.doi}')
    return '\n\n'.join(lines)
