import unittest
import pandas as pd
from source_catalog_visibility import include_extracted_library, unified_numeric_sources


class CompleteCatalogTests(unittest.TestCase):
    def test_adds_numeric_library_without_fabricating_patient_matches(self):
        scoped = pd.DataFrame([dict(paper_id='pd', doi='PD', source_title='PD', quantitative_records=2,
                                    matched_group_effect_features=3)])
        library = pd.DataFrame([
            dict(paper_id='pd', doi='pd', source_title='PD', quantitative_records=2),
            dict(paper_id='ad', doi='ad', source_title='AD', quantitative_records=4),
            dict(paper_id='empty', doi='empty', source_title='Empty', quantitative_records=0)])
        merged = include_extracted_library(scoped, library)
        shown = unified_numeric_sources(merged)
        self.assertEqual(set(shown.doi), {'pd', 'ad'})
        self.assertEqual(shown.loc[shown.doi.eq('ad'), 'patient_comparisons'].iloc[0], 'Not directly compared')
        self.assertIn('3 group-effect matches', shown.loc[shown.doi.eq('pd'), 'patient_comparisons'].iloc[0])
        self.assertEqual(scoped.iloc[0].doi, 'PD')

    def test_repeated_merge_does_not_duplicate_sources(self):
        library = pd.DataFrame([dict(paper_id='one', doi='one', source_title='One', quantitative_records=1)])
        self.assertEqual(len(include_extracted_library(include_extracted_library(library, library), library)), 1)
