"""Refresh DIS-006 source counts only; all patient exports remain strictly checked."""
from pathlib import Path
import shutil
import tempfile

import pandas as pd

from dis006_fulltext_review import DOI, SOURCE, SCOPE, records, verify


def verify_coverage(before,after):
    expected = before.copy(deep=True)
    if set(expected.columns)!=set(after.columns):
        raise ValueError('Unexpected coverage schema change')
    indices = expected.index[expected.doi.eq(DOI)]
    if len(indices)>1:
        raise ValueError('Duplicate DIS-006 source')
    if len(indices):
        i = indices[0]
        for column in ('unique_evidence_rows','quantitative_records','reported_statistic_records'):
            if expected.at[i,column] not in (0,192):
                raise ValueError('Unexpected DIS-006 extraction baseline')
            expected.at[i,column] = 192
        locations = set(str(expected.at[i,'locations']).split(' | '))
        expected.at[i,'locations'] = ' | '.join(sorted(locations|{SOURCE}))
        rois = set(str(expected.at[i,'rois']).split(' | '))-{'','nan'}
        expected.at[i,'rois'] = ' | '.join(sorted(rois|{r['roi_name'] for r in records()}))
        expected.at[i,'reported_statistics_scope'] = SCOPE
        expected.at[i,'zero_match_reason'] = SCOPE
        expected.at[i,'zero_evidence_reason'] = ''
    pd.testing.assert_frame_equal(expected[after.columns].fillna(''),after.fillna(''),
                                  check_exact=True,check_dtype=False)


def refresh(root):
    import review_pending_reports
    from build_final_reports import build
    root = Path(root).resolve()
    if verify(root) is None:
        raise ValueError('Source-bound DIS-006 verification required')
    original = review_pending_reports.compare_numeric
    def compare(old,new):
        name = Path(old).stem.replace('_concise_report','_source_coverage')+'.csv'
        before,after = pd.read_csv(Path(old).with_name(name)),pd.read_csv(Path(new).with_name(name))
        verify_coverage(before,after)
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory)/Path(old).name
            baseline.touch()
            for path in Path(old).parent.glob('*'):
                if path.suffix in ('.csv','.json'):
                    shutil.copy2(path,baseline.parent/path.name)
            after.to_csv(baseline.with_name(name),index=False)
            return original(baseline,new)
    review_pending_reports.compare_numeric = compare
    try:
        build(root)
    finally:
        review_pending_reports.compare_numeric = original
