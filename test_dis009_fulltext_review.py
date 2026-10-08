import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from dis009_fulltext_review import DOI, SOURCE, MANIFEST, PDF, TABLE, SCOPE, records, verify, render
from literature_audit import build_literature_audit, qualitative_candidates
from refresh_dis009_reports import verify_coverage

ROOT = Path(__file__).resolve().parent


class Dis009Tests(unittest.TestCase):
    def test_exact_table2_mean_sd_p_values_and_n(self):
        data = verify(ROOT)
        self.assertEqual(TABLE, [('lh',12,.02,1.25,4.50,3.29,'<'),
            ('lh',6,.26,2.39,4.12,4.22,'='), ('rh',12,.52,1.37,4.68,3.23,'<'),
            ('rh',6,.54,2.45,3.81,3.16,'='), ('total_left_plus_right',12,.28,.93,4.57,2.98,'<'),
            ('total_left_plus_right',6,.41,1.69,3.95,3.01,'<')])
        self.assertEqual(data['statistic_records'],12)
        self.assertEqual(len({r['comparison_id'] for r in records()}),6)
        self.assertEqual([r['cohort_sample_size'] for r in records()], [20,36]*6)
        self.assertTrue(all(r['unit'] == '%/year' and r['standard_deviation'] is not None
                            and r['confidence_interval_lower'] is None for r in records()))

    def test_no_double_annualization_or_invented_formula(self):
        data = verify(ROOT)
        self.assertIn('do not multiply', data['annualization'])
        self.assertIn('do not add or average', data['total_definition'])
        for field in ('annualization_equation','days_per_year_convention',
                      'six_month_scan_pair_aggregation','individual_diagnostic_threshold'):
            self.assertIsNone(data[field])
        self.assertIn('0.41 versus 0.28', data['source_text_discrepancy'])

    def test_source_counts_are_not_patient_matches_or_human_approval(self):
        audit = build_literature_audit(ROOT)
        paper = audit['papers'].set_index('doi').loc[DOI]
        self.assertEqual(paper.unique_evidence_rows,12)
        self.assertEqual(paper.reported_statistic_records,12)
        self.assertEqual(paper.group_distribution_rows,0)
        self.assertEqual(paper.human_accepted_rows,0)
        audit['evidence'].loc[audit['evidence'].doi.eq(DOI),'manual_review_status'] = 'accepted'
        self.assertFalse(any(r['doi'] == DOI for r in qualitative_candidates(audit)))
        self.assertTrue(all(not r['numeric_use'] and not r['comparison_compatible'] for r in records()))
        from workflow_audit import source_coverage
        result = dict(papers=audit['papers'], links=pd.DataFrame(), project_dir=ROOT)
        with patch('pd_evidence.compare_result',return_value=[]), patch('pd_evidence.compare_stage_result',return_value=[]), patch('pd_reviewed_comparison.coverage',return_value=pd.DataFrame()), patch('reference_focus.pd_only',return_value=True):
            covered = source_coverage(result,'test').set_index('doi').loc[DOI]
        self.assertEqual(covered.paired_features_exploratory,0)
        self.assertEqual(covered.zero_match_reason,SCOPE)

    def test_clean_presentation_and_resolved_source_summary(self):
        from research_report_release import final_frame, assert_final_text
        from zero_paper_review import review_for
        shown = final_frame(pd.DataFrame(records()))
        self.assertTrue(shown.evidence_disposition.str.contains('Verified full-text').all())
        assert_final_text(render(ROOT))
        self.assertNotIn('not obtained', review_for(dict(doi=DOI,legacy_codes='DIS-009'))['source_location'])

    def test_missing_or_changed_primary_source_and_stats_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (MANIFEST,SOURCE,PDF):
                target = root / name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT / name,target)
            verify(root)
            rows = records()
            rows[0]['reported_value'] = .04
            (root / SOURCE).write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError,'Table 2'):
                verify(root)
            (root / PDF).unlink()
            with self.assertRaisesRegex(ValueError,'primary PDF'):
                verify(root)

    def test_refresh_allows_only_dis009_count_and_scope_cells(self):
        after = build_literature_audit(ROOT)['papers'].copy()
        after['zero_match_reason'] = ''
        hit = after.doi.eq(DOI)
        after.loc[hit,'zero_match_reason'] = SCOPE
        before = after.copy()
        before.loc[hit,['unique_evidence_rows','quantitative_records','reported_statistic_records']] = 0
        before.loc[hit,'locations'] = before.loc[hit,'locations'].str.replace(' | '+SOURCE,'',regex=False)
        before.loc[hit,'reported_statistics_scope'] = ''
        before.loc[hit,'zero_evidence_reason'] = 'Source registered; no extracted records in connected evidence files'
        before.loc[hit,'zero_match_reason'] = 'Catalog entry only; no extracted evidence in a connected data store'
        verify_coverage(before,after)
        verify_coverage(after,after)
        verify_coverage(before.loc[~hit].reset_index(drop=True),after.loc[~hit].reset_index(drop=True))
        for column,value in [('human_accepted_rows',12),('paired_features_exploratory',1)]:
            start,changed = before.copy(), after.copy()
            if column not in start:
                start[column] = changed[column] = 0
            changed.loc[hit,column] = value
            with self.assertRaises(AssertionError):
                verify_coverage(start,changed)
        changed = after.copy()
        changed.loc[~hit,'unique_evidence_rows'] += 1
        with self.assertRaises(AssertionError):
            verify_coverage(before,changed)


if __name__ == '__main__':
    unittest.main()
