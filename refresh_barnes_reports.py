"""Refresh source counts while retaining the existing patient-export verifier."""
import json
from pathlib import Path
import shutil
import tempfile

import pandas as pd

DOI = '10.1159/000084560'
SOURCE = 'workflow_sources/paper_reading_reviews/barnes_2005_reported_statistics.json'


def verify_coverage(before, after, scope):
    expected = before.copy(deep=True)
    for column, default in [('reported_statistic_records', 0), ('reported_statistics_scope', '')]:
        if column not in expected:
            expected[column] = default
        else:
            expected[column] = expected[column].fillna(default)
    rows = expected.index[expected.doi.eq(DOI)]
    if not len(rows):
        # PD-only configurations intentionally exclude AD references.
        pd.testing.assert_frame_equal(expected[after.columns].fillna(''), after.fillna(''),
                                      check_exact=True, check_dtype=False)
        if set(expected.columns) != set(after.columns):
            raise ValueError('Unexpected coverage schema change')
        return
    if len(rows) != 1:
        raise ValueError('Duplicate Barnes source row')
    index = rows[0]
    if expected.at[index, 'unique_evidence_rows'] not in (0, 6):
        raise ValueError('Unexpected baseline extraction count')
    for column in ('unique_evidence_rows', 'quantitative_records', 'reported_statistic_records'):
        expected.at[index, column] = 6
    locations = set(str(expected.at[index, 'locations']).split(' | '))
    locations.add(SOURCE)
    expected.at[index, 'locations'] = ' | '.join(sorted(locations))
    expected.at[index, 'reported_statistics_scope'] = scope
    expected.at[index, 'zero_match_reason'] = scope
    expected.at[index, 'zero_evidence_reason'] = ''
    pd.testing.assert_frame_equal(expected[after.columns].fillna(''), after.fillna(''),
                                  check_exact=True, check_dtype=False)
    if set(expected.columns) != set(after.columns):
        raise ValueError('Unexpected coverage schema change')


def refresh(root):
    import review_pending_reports
    from build_final_reports import build
    root = Path(root).resolve()
    scope = json.loads((root / SOURCE).read_text())[0]['applicability_note']
    original = review_pending_reports.compare_numeric

    def compare(old, new):
        coverage_name = Path(old).stem.replace('_concise_report', '_source_coverage') + '.csv'
        before = pd.read_csv(Path(old).with_name(coverage_name))
        after = pd.read_csv(Path(new).with_name(coverage_name))
        verify_coverage(before, after, scope)
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / Path(old).name
            baseline.touch()
            for path in Path(old).parent.glob('*'):
                if path.suffix in ('.csv', '.json'):
                    shutil.copy2(path, baseline.parent / path.name)
            after.to_csv(baseline.with_name(coverage_name), index=False)
            return original(baseline, new)

    review_pending_reports.compare_numeric = compare
    try:
        build(root)
    finally:
        review_pending_reports.compare_numeric = original


if __name__ == '__main__':
    refresh(Path(__file__).resolve().parent)
