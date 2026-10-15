"""Patient-facing source catalog only shows numeric contributors."""
import unittest

import pandas as pd

from source_catalog_visibility import other_numeric_sources, patient_numeric_sources, patient_source_summary, unified_numeric_sources


class SourceCatalogVisibilityTests(unittest.TestCase):
    def test_unified_catalog_retains_all_numeric_sources_once(self):
        papers = pd.DataFrame([
            dict(source_title='Context', doi='c', quantitative_records=70),
            dict(source_title='Matched', doi='m', quantitative_records=5, paired_features_exploratory=3),
            dict(source_title='Empty', doi='e')])
        shown = unified_numeric_sources(papers)
        self.assertEqual(shown.source_title.tolist(), ['Context', 'Matched'])
        self.assertEqual(shown.patient_comparisons.tolist(), ['Not directly compared', '3 exploratory paired features'])
        self.assertFalse(shown.isna().any().any())

    def test_keeps_numeric_matches_from_each_store_without_missing_cells(self):
        papers = pd.DataFrame([
            dict(source_title='Sokolowski', doi='s', additional_quantitative_records=85,
                 additional_descriptive_comparisons=0),
            dict(source_title='Hanganu', doi='h', additional_quantitative_records=44,
                 additional_descriptive_comparisons=0),
            dict(source_title='Mak', doi='m', additional_quantitative_records=84,
                 additional_descriptive_comparisons=42),
            dict(source_title='Gerrits', doi='g', additional_quantitative_records=25,
                 additional_descriptive_comparisons=0),
            dict(source_title='ENIGMA', doi='e', matched_group_effect_features=152),
            dict(source_title='Zheng', doi='z', paired_features_exploratory=140),
        ])
        before = papers.copy(deep=True)
        shown = patient_numeric_sources(papers)
        self.assertEqual(shown.source_title.tolist(), ['Mak', 'ENIGMA', 'Zheng'])
        self.assertEqual(shown.additional_descriptive_comparisons.tolist(), [42, 0, 0])
        self.assertEqual(shown.matched_group_effect_features.tolist(), [0, 152, 0])
        self.assertFalse(shown.isna().any().any())
        pd.testing.assert_frame_equal(papers, before)

    def test_empty_catalog_has_no_false_contributors(self):
        papers = pd.DataFrame([dict(source_title='Context only', doi='c')])
        self.assertTrue(patient_numeric_sources(papers).empty)

    def test_patient_summary_avoids_misleading_zero_columns(self):
        papers = pd.DataFrame([
            dict(source_title='ENIGMA', doi='e', matched_group_effect_features=152,
                 matched_stage_features=608),
            dict(source_title='Zheng', doi='z', paired_features_exploratory=140),
            dict(source_title='Mak', doi='m', additional_descriptive_comparisons=42),
        ])
        shown = patient_source_summary(papers)
        self.assertEqual(shown.columns.tolist(), ['source_title', 'doi', 'patient_comparisons'])
        self.assertEqual(shown.patient_comparisons.tolist(), [
            '152 group-effect matches; 608 stage-context matches',
            '140 exploratory paired features', '42 descriptive comparisons'])

    def test_other_numeric_sources_keep_context_without_zero_only_papers(self):
        papers = pd.DataFrame([
            dict(source_title='Sokolowski', doi='s', additional_quantitative_records=85),
            dict(source_title='Hanganu', doi='h', additional_quantitative_records=44),
            dict(source_title='Gerrits', doi='g', additional_quantitative_records=25),
            dict(source_title='Barnes', doi='b', quantitative_records=6),
            dict(source_title='ENIGMA', doi='e', connected_group_effect_records=152,
                 matched_group_effect_features=152),
            dict(source_title='No numeric evidence', doi='n', qualitative_records=2),
        ])
        context = other_numeric_sources(papers)
        self.assertEqual(context.source_title.tolist(),
                         ['Sokolowski', 'Hanganu', 'Gerrits', 'Barnes'])
        self.assertEqual(context.extracted_numeric_evidence.tolist(), [
            '85 reviewed PD table records', '44 reviewed PD table records',
            '25 reviewed PD table records', '6 registry numeric records'])
        self.assertFalse(context.isna().any().any())


if __name__ == '__main__':
    unittest.main()
