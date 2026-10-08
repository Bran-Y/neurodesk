"""Allow only the two verified source-coverage changes during report regeneration."""
from pathlib import Path
import shutil
import tempfile
import pandas as pd
from hippocampal_fulltext_review import DOIS, SOURCE, SCOPES, verify


def verify_coverage(before,after):
    expected=before.copy(deep=True)
    if set(expected.columns)!=set(after.columns):
        raise ValueError('Unexpected source schema change')
    for code,doi in DOIS.items():
        indices=expected.index[expected.doi.eq(doi)]
        if len(indices)>1:
            raise ValueError('Duplicate hippocampal source')
        if not len(indices):
            continue
        i=indices[0]
        n,old=(6,0) if code=='ROI-006' else (3,1)
        for column,prior,total in [('unique_evidence_rows',old,old+n),
                                   ('quantitative_records',0,n),('reported_statistic_records',0,n)]:
            if expected.at[i,column] not in (prior,total):
                raise ValueError('Unexpected hippocampal baseline: '+column)
            expected.at[i,column]=total
        locations=set(str(expected.at[i,'locations']).split(' | '))
        expected.at[i,'locations']=' | '.join(sorted(locations|{SOURCE}))
        expected.at[i,'reported_statistics_scope']=SCOPES[code]
        expected.at[i,'zero_match_reason']=SCOPES[code]
        expected.at[i,'zero_evidence_reason']=''
    pd.testing.assert_frame_equal(expected[after.columns].fillna(''),after.fillna(''),check_exact=True,check_dtype=False)


def refresh(root):
    import review_pending_reports
    from build_final_reports import build
    root=Path(root).resolve()
    if verify(root) is None:
        raise ValueError('Verified primary sources required')
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
