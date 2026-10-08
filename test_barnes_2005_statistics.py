import json
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd
from literature_audit import build_literature_audit, qualitative_candidates
from workflow_audit import source_coverage
from refresh_barnes_reports import verify_coverage


ROOT = Path(__file__).resolve().parent
DOI = '10.1159/000084560'


class BarnesStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.audit = build_literature_audit(ROOT)

    def test_extracted_counts_do_not_imply_human_approval(self):
        paper = self.audit['papers'].set_index('doi').loc[DOI]
        self.assertEqual(paper.unique_evidence_rows, 6)
        self.assertEqual(paper.quantitative_records, 6)
        self.assertEqual(paper.reported_statistic_records, 6)
        self.assertEqual(paper.group_distribution_rows, 0)
        self.assertEqual(paper.human_accepted_rows, 0)
        self.assertEqual(paper.zero_evidence_reason, '')

    def test_values_and_ci_are_not_sd_or_prediction_intervals(self):
        records = json.loads((ROOT / 'workflow_sources/paper_reading_reviews/barnes_2005_reported_statistics.json').read_text())
        self.assertEqual([r['reported_value'] for r in records], [1.7, 1.8, 1.2, 1.1, 4.6, 6.3])
        self.assertEqual([r['confidence_interval_lower'] for r in records], [-0.3, -1.9, 0.5, 0.5, 3.3, 4.9])
        self.assertEqual([r['confidence_interval_upper'] for r in records], [3.7, 5.5, 1.8, 1.8, 6.0, 7.8])
        for row in records:
            self.assertIsNone(row['standard_deviation'])
            self.assertIsNone(row['confidence_level'])
            self.assertFalse(row['numeric_use'])
            self.assertFalse(row['comparison_compatible'])
            self.assertNotIn('lower_95pi', row)

    def test_reported_statistics_never_become_volume_links_even_if_approved(self):
        audit = dict(self.audit)
        audit['evidence'] = audit['evidence'].copy()
        audit['evidence'].loc[audit['evidence'].doi.eq(DOI), 'manual_review_status'] = 'accepted'
        self.assertFalse(any(str(r.get('doi', '')).lower() == DOI for r in qualitative_candidates(audit)))

    def test_zero_match_reason_is_specific_not_missing_extraction(self):
        result = {'papers': self.audit['papers'], 'links': pd.DataFrame(), 'project_dir': ROOT}
        with patch('pd_evidence.compare_result', return_value=[]), patch('pd_evidence.compare_stage_result', return_value=[]), patch('pd_reviewed_comparison.coverage', return_value=pd.DataFrame()), patch('reference_focus.pd_only', return_value=True):
            paper = source_coverage(result, 'test_case').set_index('doi').loc[DOI]
        self.assertEqual(paper.connected_group_effect_records, 0)
        self.assertIn('serial MRI', paper.zero_match_reason)
        self.assertNotIn('Catalog entry only', paper.zero_match_reason)

    def test_refresh_allows_only_the_extracted_source_count_changes(self):
        # Exercise the historical schema migration before other context tables were connected.
        after = self.audit['papers'].loc[~self.audit['papers'].doi.isin(
            ['10.1016/j.neurobiolaging.2007.02.011','10.1159/000258100',
             '10.1212/wnl.0b013e3181a4124e','10.1097/rct.0b013e31802f4139',
             '10.1016/j.neuroimage.2008.10.043','10.1016/j.neuroimage.2010.06.025'])].reset_index(drop=True).copy()
        after['zero_match_reason'] = ''
        hit = after.doi.eq(DOI)
        scope = after.loc[hit, 'reported_statistics_scope'].iloc[0]
        after.loc[hit, 'zero_match_reason'] = scope
        before = after.drop(columns=['reported_statistic_records', 'reported_statistics_scope']).copy()
        before.loc[hit, ['unique_evidence_rows', 'quantitative_records']] = 0
        before.loc[hit, 'locations'] = before.loc[hit, 'locations'].str.replace(
            ' | workflow_sources/paper_reading_reviews/barnes_2005_reported_statistics.json', '', regex=False)
        before.loc[hit, 'zero_evidence_reason'] = 'Source registered; no extracted records in connected evidence files'
        before.loc[hit, 'zero_match_reason'] = 'Catalog entry only; no extracted evidence in a connected data store'
        verify_coverage(before, after, scope)
        repeat = after.copy()
        repeat.loc[~hit, 'reported_statistic_records'] = float('nan')
        verify_coverage(repeat, after, scope)
        verify_coverage(before.loc[~hit].reset_index(drop=True),
                        after.loc[~hit].reset_index(drop=True), scope)
        for column, value in [('human_accepted_rows', 6), ('unique_evidence_rows', 7)]:
            changed = after.copy()
            changed.loc[hit, column] = value
            with self.assertRaises(AssertionError):
                verify_coverage(before, changed, scope)
        changed = after.copy()
        changed.loc[~hit, 'unique_evidence_rows'] += 1
        with self.assertRaises(AssertionError):
            verify_coverage(before, changed, scope)


if __name__ == '__main__':
    unittest.main()
