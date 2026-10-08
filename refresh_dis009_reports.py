"""Allow only a source-coverage refresh; retain strict patient-value comparisons."""
import json
from pathlib import Path
import shutil
import tempfile

import pandas as pd

from dis009_fulltext_review import DOI, SOURCE, SCOPE, verify


def verify_coverage(before, after):
    expected = before.copy(deep=True)
    if set(expected.columns) != set(after.columns):
        raise ValueError('Unexpected coverage schema change')
    rows = expected.index[expected.doi.eq(DOI)]
    if len(rows) > 1:
        raise ValueError('Duplicate DIS-009 source')
    if len(rows):
        index = rows[0]
        for column in ('unique_evidence_rows','quantitative_records','reported_statistic_records'):
            if expected.at[index,column] not in (0,12):
                raise ValueError('Unexpected DIS-009 baseline extraction count')
            expected.at[index,column] = 12
        locations = set(str(expected.at[index,'locations']).split(' | '))
        locations.add(SOURCE)
        expected.at[index,'locations'] = ' | '.join(sorted(locations))
        rois = set(str(expected.at[index,'rois']).split(' | ')) - {'', 'nan'}
        expected.at[index,'rois'] = ' | '.join(sorted(rois | {'hippocampus'}))
        expected.at[index,'reported_statistics_scope'] = SCOPE
        expected.at[index,'zero_match_reason'] = SCOPE
        expected.at[index,'zero_evidence_reason'] = ''
    pd.testing.assert_frame_equal(expected[after.columns].fillna(''), after.fillna(''),
                                  check_exact=True, check_dtype=False)


def refresh(root):
    import review_pending_reports
    from build_final_reports import build
    root = Path(root).resolve()
    if verify(root) is None:
        raise ValueError('Source-bound DIS-009 verification required')
    original = review_pending_reports.compare_numeric

    def compare(old, new):
        name = Path(old).stem.replace('_concise_report','_source_coverage') + '.csv'
        before, after = pd.read_csv(Path(old).with_name(name)), pd.read_csv(Path(new).with_name(name))
        verify_coverage(before, after)
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / Path(old).name
            baseline.touch()
            for path in Path(old).parent.glob('*'):
                if path.suffix in ('.csv','.json'):
                    shutil.copy2(path, baseline.parent / path.name)
            # Only the independently verified source-coverage cells are normalized.
            after.to_csv(baseline.with_name(name), index=False)
            return original(baseline, new)

    review_pending_reports.compare_numeric = compare
    try:
        build(root)
    finally:
        review_pending_reports.compare_numeric = original


if __name__ == '__main__':
    refresh(Path(__file__).resolve().parent)
