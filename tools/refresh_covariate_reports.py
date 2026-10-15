"""Refresh method context while strictly preserving patient measurements and interpretation."""
from pathlib import Path
import shutil
import tempfile
import pandas as pd
from covariate_fulltext_review import DOI, SOURCE, SCOPE, records, verify


def verify_coverage(before, after):
    expected=before.copy(deep=True)
    if set(expected.columns)!=set(after.columns):
        raise ValueError('Unexpected source schema change')
    indices=expected.index[expected.doi.eq(DOI)]
    if len(indices)>1:
        raise ValueError('Duplicate covariate source')
    if len(indices):
        i=indices[0]
        for column in ('unique_evidence_rows','quantitative_records','reported_statistic_records'):
            if expected.at[i,column] not in (0,56):
                raise ValueError('Unexpected covariate baseline: '+column)
            expected.at[i,column]=56
        locations=set(str(expected.at[i,'locations']).split(' | '))
        expected.at[i,'locations']=' | '.join(sorted(locations|{SOURCE}))
        rois=set(str(expected.at[i,'rois']).split(' | '))
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
        raise ValueError('Verified primary PDF required')
    original=review_pending_reports.compare_numeric
    def compare(old,new):
        name=Path(old).stem.replace('_concise_report','_source_coverage')+'.csv'
        before=pd.read_csv(Path(old).with_name(name))
        after=pd.read_csv(Path(new).with_name(name))
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
