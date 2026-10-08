"""Shared, auditable naming boundary for patient and reference comparisons.

Name alignment never changes measurement units, atlas identity or review approval.
"""
from pathlib import Path
import json
from functools import lru_cache
import pandas as pd
from neurodesk_literature_to_pgsql import (
    apply_atlas_translation, atlas_code_from_label, normalize_hemisphere_label,
    resolve_atlas_from_source_file,
)


DEFAULT_REGISTRY = Path(__file__).parent / 'workflow_sources/atlas_translation/atlas_translation_registry.json'


def _text(value):
    return '' if value is None or pd.isna(value) else str(value).strip().lower()


@lru_cache(maxsize=8)
def _registry(path, mtime_ns, size):
    return json.loads(Path(path).read_text())['mappings']


def translate_records(records, registry_path=None):
    """Resolve exact source/standard labels within an atlas; never fuzzy-match ROI extent."""
    path = Path(registry_path or DEFAULT_REGISTRY)
    stat = path.stat()
    mappings = _registry(str(path), stat.st_mtime_ns, stat.st_size)
    output = []
    for source in records:
        row = dict(source)
        roi = _text(row.get('source_roi_name', row.get('roi_name')))
        hemi = normalize_hemisphere_label(row.get('hemisphere'))
        for prefix, side in [('left-', 'lh'), ('left_', 'lh'), ('right-', 'rh'), ('right_', 'rh')]:
            if roi.startswith(prefix):
                if hemi and hemi != side:
                    row['comparison_mapping_error'] = 'ROI prefix and hemisphere conflict'
                hemi = hemi or side
        atlas = atlas_code_from_label(row.get('atlas_name'))
        file_atlas = resolve_atlas_from_source_file(row.get('source_file'))['atlas_code']
        if atlas != 'unknown_atlas' and file_atlas != 'unknown_atlas' and atlas != file_atlas:
            row['comparison_mapping_error'] = 'Atlas label and source file conflict'
        candidates = []
        for mapping in mappings:
            code = mapping.get('source_atlas_code') or atlas_code_from_label(mapping.get('source_atlas_name'))
            side = normalize_hemisphere_label(mapping.get('hemisphere'))
            if atlas == 'unknown_atlas' or code != atlas or (side and side != hemi):
                continue
            if roi in (_text(mapping.get('source_roi_name')), _text(mapping.get('standard_roi_name'))):
                candidates.append(mapping)
        identities = {(_text(m['standard_roi_name']), normalize_hemisphere_label(m.get('hemisphere')) or hemi,
                       m.get('mapping_relation'), m.get('manual_review_status')) for m in candidates}
        row.update(source_roi_name=row.get('source_roi_name', row.get('roi_name')),
                   source_hemisphere=row.get('source_hemisphere', row.get('hemisphere')),
                   comparison_registry=str(path), comparison_atlas_code=atlas)
        if len(identities) == 1:
            name, side, relation, status = next(iter(identities))
            row.update(standard_roi_name=name, standard_hemisphere=side,
                       mapping_relation=relation, atlas_translation_review_status=status)
            if relation not in ('exact', 'unassessed'):
                native = { _text(m['source_roi_name']) for m in candidates }
                if relation in ('broader_than_source', 'narrower_than_source') and roi in native and len(native) == 1:
                    # Keep the native parcel identity: never compare it as the broader target ROI.
                    row['standard_roi_name'] = atlas + ':' + roi
                    row['comparison_naming_scope'] = 'same_native_parcel_only'
                else:
                    row['comparison_mapping_error'] = 'Non-exact anatomical mapping: ' + str(relation)
        else:
            row.update(standard_roi_name=None, standard_hemisphere=hemi,
                       atlas_translation_review_status='pending_human_review')
            row['comparison_mapping_error'] = 'Ambiguous atlas mapping' if candidates else 'No atlas-specific registry mapping'
        row['standard_imaging_metric'] = _text(row.get('imaging_metric'))
        output.append(row)
    return output


def prepare_features(frame, registry_path=None):
    """Keep all rows, raw metadata and the original Atlas Translation audit columns."""
    if frame.empty:
        return frame.copy()
    translated = apply_atlas_translation(frame, registry_path or DEFAULT_REGISTRY)
    # The legacy audit normalizer infers units. Do not allow that at the comparison boundary.
    translated['unit'] = frame['unit'].to_numpy() if 'unit' in frame else None
    if 'hemisphere' in frame:
        translated['hemisphere'] = frame['hemisphere'].to_numpy()
    records = translate_records(translated.to_dict('records'), registry_path)
    return pd.DataFrame(records, index=frame.index)


def comparison_features(result):
    if 'comparison_features' in result:
        return result['comparison_features']
    path = result.get('run_manifest', {}).get('atlas_translation_registry')
    if path and not Path(path).exists():
        # Saved remote manifests may be inspected in a local checkout.
        path = Path(result.get('project_dir', DEFAULT_REGISTRY.parent.parent.parent)) / 'workflow_sources/atlas_translation/atlas_translation_registry.json'
    return prepare_features(result['features'], path)


def feature_key(row):
    if 'comparison_registry' not in row:
        row = translate_records([row])[0]
    if _text(row.get('comparison_mapping_error')):
        # Callers must reject mapping_error before treating this audit key as a match.
        return ('unmapped:' + _text(row.get('roi_name')), _text(row.get('standard_hemisphere')),
                _text(row.get('standard_imaging_metric')))
    return (_text(row.get('standard_roi_name')), _text(row.get('standard_hemisphere')),
            _text(row.get('standard_imaging_metric')))


def mapping_error(row):
    from segmentation_holds import reason
    if reason(row):
        return reason(row)
    return _text(row.get('comparison_mapping_error'))
