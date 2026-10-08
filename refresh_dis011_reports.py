"""Refresh one verified FTLD source; keep patient exports and interpretations fixed."""
from pathlib import Path
import shutil
import tempfile
import pandas as pd
from dis011_fulltext_review import DOI, SOURCE, SCOPE, records, verify


def verify_coverage(before,after):
    expected = before.copy(deep=True)
    if set(expected.columns)!=set(after.columns):
        raise ValueError('Unexpected source schema change')
    indices = expected.index[expected.doi.eq(DOI)]
    if len(indices)>1:
        raise ValueError('Duplicate DIS-011 source')
    if len(indices):
        i=indices[0]
        for column,prior,total in [('unique_evidence_rows',1,43),('quantitative_records',0,42),('reported_statistic_records',0,42)]:
            if expected.at[i,column] not in (prior,total):
                raise ValueError('Unexpected DIS-011 baseline: '+column)
            expected.at[i,column]=total
        locations=set(str(expected.at[i,'locations']).split(' | '))
        expected.at[i,'locations']=' | '.join(sorted(locations|{SOURCE}))
        rois=set(str(expected.at[i,'rois']).split(' | '))-{'','nan'}
        expected.at[i,'rois']=' | '.join(sorted(rois|{r['roi_name'] for r in records()}))
        expected.at[i,'reported_statistics_scope']=SCOPE
        expected.at[i,'zero_match_reason']=SCOPE
        expected.at[i,'zero_evidence_reason']=''
    pd.testing.assert_frame_equal(expected[after.columns].fillna(''),after.fillna(''),check_exact=True,check_dtype=False)


def refresh(root):
    import review_pending_reports
    from build_final_reports import build
    root=Path(root).resolve()
    if verify(root) is None:
        raise ValueError('Verified primary source required')
    original=review_pending_reports.compare_numeric
    def compare(old,new):
        name=Path(old).stem.replace('_concise_report','_source_coverage')+'.csv'
        before,after=pd.read_csv(Path(old).with_name(name)),pd.read_csv(Path(new).with_name(name))
        verify_coverage(before,after)
        with tempfile.TemporaryDirectory() as directory:
            baseline=Path(directory)/Path(old).name
            baseline.touch()
            for path in Path(old).parent.glob('*'):
                if path.suffix in ('.csv','.json'):
                    shutil.copy2(path,baseline.parent/path.name)
            after.to_csv(baseline.with_name(name),index=False)
            return original(baseline,new)
    review_pending_reports.compare_numeric=compare
    try:
        build(root)
    finally:
        review_pending_reports.compare_numeric=original
