"""Temporary, source-bound measurement holds; never edit anatomy or grant QC."""
import html
import json
from pathlib import Path

import pandas as pd

POLICY = 'outputs/segmentation_holds/active_holds.json'
DERIVED = ('expected_value', 'lower_95pi', 'upper_95pi', 'zop', 'percentile',
           'prediction_se', 'expected_direction', 'model_id')


def reason(row):
    value = row.get('qc_hold_reason', '')
    return '' if value is None or pd.isna(value) else str(value).strip()


def policies(result):
    path = Path(result.get('project_dir', '.')) / POLICY
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if data.get('schema_version') != 1:
        raise ValueError('Unsupported segmentation hold policy')
    records = data['holds']
    seen = set()
    for item in records:
        if item['subject_id'] in seen or item['status'] not in ('active', 'resolved'):
            raise ValueError('Invalid or duplicate segmentation hold')
        seen.add(item['subject_id'])
        if item['scope'] not in ('subject', 'roi') or not item['reason'].strip():
            raise ValueError('Invalid segmentation hold scope/reason')
        if item['scope'] == 'roi' and not item.get('roi_names'):
            raise ValueError('ROI hold requires explicit native names')
        if item['status'] == 'resolved' and not item.get('resolution_record'):
            raise ValueError('Hold release requires a separate review resolution')
        if item['status'] == 'resolved':
            from report_quality import read_qc
            qc = read_qc(result, item['subject_id'])
            if qc['status'] != 'accepted' or item['resolution_record'].get('source_fingerprint') != qc.get('source_fingerprint'):
                raise ValueError('Hold release requires accepted QC bound to current source')
    return [r for r in records if r['status'] == 'active']


def annotate_features(result, frame):
    """Preserve every raw value; a source change never silently clears a hold."""
    records = policies(result)
    if not records:
        return frame.copy()
    from report_quality import source_fingerprint
    out = frame.copy()
    out['qc_hold_reason'] = ''
    for item in records:
        selected = out.subject_id.eq(item['subject_id'])
        if not selected.any():
            continue
        fingerprint, missing = source_fingerprint(result['fs_root'], item['subject_id'])
        note = item['reason']
        if fingerprint != item['source_fingerprint'] or missing:
            note += ' Source changed or is incomplete; review current data before release.'
        if item['scope'] == 'roi':
            selected &= out.roi_name.isin(item['roi_names'])
        out.loc[selected, 'qc_hold_reason'] = note
    return out


def apply_normative_holds(features, normative):
    if 'qc_hold_reason' not in features:
        return normative.copy()
    keys = ['subject_id', 'roi_name', 'hemisphere', 'imaging_metric']
    held = features.loc[features.qc_hold_reason.map(reason_value).ne(''), keys + ['qc_hold_reason']]
    if held.duplicated(keys).any():
        raise ValueError('Duplicate held measurement identity')
    reasons = {tuple(r[k] for k in keys): reason(r) for r in held.to_dict('records')}
    out = normative.copy()
    if reasons:
        # Preserve the export schema even when every model was skipped by QC.
        for field in DERIVED:
            if field not in out:
                out[field] = None
    for index, row in out.iterrows():
        note = reasons.get(tuple(row[k] for k in keys))
        if note:
            out.loc[index, 'calculation_status'] = 'not_calculated'
            out.loc[index, 'range_status'] = 'not_assessed'
            out.loc[index, 'exclusion_reason'] = note
            out.loc[index, 'method_note'] = note
            for field in DERIVED:
                out.loc[index, field] = None
    return out


def reason_value(value):
    return reason({'qc_hold_reason': value})


def hold_html(result, subject_id):
    from comparison_atlas import comparison_features
    frame = comparison_features(result)
    if 'qc_hold_reason' not in frame:
        return ''
    held = frame.loc[frame.subject_id.eq(subject_id) & frame.qc_hold_reason.map(reason_value).ne('')]
    if held.empty:
        return ''
    notes = '; '.join(held.qc_hold_reason.unique())
    return ('<p role="alert"><b>QC exclusion: ' + str(len(held)) + ' measurement(s).</b> ' +
            html.escape(notes) + ' Raw measurements are retained, but excluded from normative '
            'interpretation and patient-reference comparisons. This is a precaution, not a '
            'confirmed segmentation failure or a disease finding.</p>')
