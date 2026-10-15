"""Explicit reference selection, never inferred from identity or diagnosis."""
PD_DOI = '10.1002/mds.28706'
POTVIN_DOI = '10.1016/j.neuroimage.2017.05.019'
ADDITIONAL_PD_DOIS = ('10.1371/journal.pone.0295069', '10.1093/brain/awu036',
                      '10.1093/brain/awv211', '10.1371/journal.pone.0148852')


def focus(config):
    value = config.get('reference_focus', 'all')
    if value not in ('all', 'PD'):
        raise ValueError('reference_focus must be all or PD')
    return value


def pd_only(config):
    return focus(config) == 'PD'


def save_focus(config, selected):
    """Persist an explicit selection; preserve relative paths and back up the input."""
    import json
    import os
    from pathlib import Path
    import tempfile
    from datetime import datetime, timezone
    selected = focus({'reference_focus': selected})
    path = Path(config['_path'])
    original = path.read_bytes()
    data = json.loads(original)
    if focus(data) != selected:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = path.with_name(path.name + '.before_reference_' + stamp)
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(original)
        data['reference_focus'] = selected
        fd, name = tempfile.mkstemp(prefix='.reference-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, indent=2)
                stream.write('\n')
            if path.read_bytes() != original:
                raise ValueError('Configuration changed during reference selection; no overwrite')
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
    config['reference_focus'] = selected
    return config


def filter_audit(audit, selected):
    if focus({'reference_focus': selected}) == 'all':
        return audit
    result = dict(audit)
    # Select the actual source records before any patient joins, not just titles.
    for key in ('papers', 'evidence'):
        frame = audit[key]
        if 'doi' not in frame:
            result[key] = frame.iloc[:0].copy()
        else:
            result[key] = frame.loc[frame.doi.isin([PD_DOI, POTVIN_DOI, *ADDITIONAL_PD_DOIS])].copy()
    return result


def pd_table(result, subject_id):
    import pandas as pd
    from pd_evidence import compare_result
    rows = compare_result(result, subject_id)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=['roi_name', 'imaging_metric', 'match_status', 'context'])
    return frame.assign(roi_name=frame.source_structure, imaging_metric=frame.metric)
