import json
from pathlib import Path
import shutil
import tempfile
import unittest

import pandas as pd

from barnes_fulltext_review import DOI, MANIFEST, verify, render
from research_report_release import final_frame, assert_final_text

ROOT = Path(__file__).resolve().parent


class BarnesFulltextTests(unittest.TestCase):
    def test_table2_values_and_mean_kind(self):
        data = verify(ROOT)
        expected = [(2715,2631,2801),(2669,2586,2754),(2683,2600,2769),(2637,2551,2727),
                    (2262,2110,2425),(2220,2075,2375),(2095,1941,2261),(2108,1970,2256),
                    (1.017,.996,1.039),(1.017,.996,1.039),(1.019,.981,1.058),(.994,.957,1.032),
                    (1.1,.5,1.8),(1.2,.5,1.8),(6.3,4.9,7.8),(4.6,3.3,6.0)]
        self.assertEqual([(r['value'],r['ci_lower'],r['ci_upper']) for r in data['records']], expected)
        self.assertEqual(sum(r['statistic_kind'] == 'geometric_mean' for r in data['records']), 12)
        self.assertEqual(data['confidence_level'], .95)

    def test_repeated_atrophy_not_extra_votes(self):
        data = verify(ROOT)
        self.assertEqual(data['new_context_statistics'], 12)
        self.assertEqual(data['overlapping_existing_statistics'], 4)
        from literature_audit import build_literature_audit, qualitative_candidates
        audit = build_literature_audit(ROOT)
        rows = audit['evidence'].loc[audit['evidence'].doi.eq(DOI)]
        self.assertEqual(len(rows), 6)
        self.assertFalse(any(r['doi'] == DOI for r in qualitative_candidates(audit)))

    def test_no_invented_sd_diagnostic_cutoff_or_human_signoff(self):
        data = verify(ROOT)
        for field in ('patient_numeric_use','patient_qc_changed','human_signatures_changed'):
            self.assertIs(data[field], False)
        self.assertIsNone(data['standard_deviation'])
        self.assertIsNone(data['individual_prediction_interval'])
        self.assertIn('MIDAS', data['measurement_method'])
        self.assertIn('Right hippocampal volume / left', data['ratio_definition'])
        self.assertIn('serial MRI', data['permitted_use'])

    def test_printed_asymmetry_not_replaced_by_rounded_ratio(self):
        data = verify(ROOT)
        old = json.loads((ROOT / 'workflow_sources/paper_reading_reviews/barnes_2005_reported_statistics.json').read_text())
        self.assertEqual(old[1]['reported_value'], 1.8)
        self.assertIsNone(old[1]['confidence_level'])
        self.assertIn('1.019', data['printed_summary_note'])
        self.assertIn('just failing', data['statistical_caution'])

    def test_presentation_updated_but_history_unchanged(self):
        original = pd.DataFrame([dict(doi=DOI, human_review_status='pending_human_review',
                                     applicability_reasons='abstract-only', zero_match_reason='formula unverified', numeric_use=False)])
        before = original.copy(deep=True)
        shown = final_frame(original)
        pd.testing.assert_frame_equal(original, before)
        self.assertIn('Verified full-text', shown.evidence_disposition.iloc[0])
        self.assertNotIn('abstract-only', shown.applicability_reasons.iloc[0])
        self.assertIn('MIDAS-to-FreeSurfer', shown.zero_match_reason.iloc[0])
        self.assertNotIn('formula unverified', shown.zero_match_reason.iloc[0])
        self.assertFalse(shown.numeric_use.iloc[0])
        assert_final_text(render(ROOT))
        from zero_paper_review import review_for
        scope = review_for({'doi':DOI,'legacy_codes':'DIS-008'})
        self.assertIn('Full-text', scope['source_review_scope'])

    def test_missing_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / MANIFEST
            target.parent.mkdir(parents=True)
            shutil.copy2(ROOT / MANIFEST, target)
            with self.assertRaisesRegex(ValueError, 'primary PDF'):
                verify(root)


if __name__ == '__main__':
    unittest.main()
