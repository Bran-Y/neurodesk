import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from mmc_normative_workflow import load_models, predict, evaluate_features, qualitative_links


class NormativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = load_models(Path(__file__).parent / 'workflow_sources/external_validators/mmc_dk_models.json')

    def feature(self):
        return dict(subject_id='test', roi_name='superiortemporal', hemisphere='lh',
                    imaging_metric='cortical_thickness', unit='mm', age=28, sex='Male',
                    value_numeric=2.5, estimated_total_intracranial_volume=1500000,
                    scanner_field_strength=1.5, scanner_manufacturer='Siemens',
                    atlas_name='Desikan-Killiany (aparc)', source_file='/test/lh.aparc.stats',
                    source_pipeline='FreeSurfer', processing_software_version='5.3.0')

    def test_all_models_at_center_against_scalar_formula(self):
        # At centering constants, female/Siemens/3T gives x=(1,0,...).
        for model in self.pack['models']:
            i = [v.lower() for v in model['terms']].index('b0')
            expected = model['beta'][i]
            result = predict(model, self.pack, self.pack['age_center'], 'Female',
                             self.pack['etiv_center'], 3, 'Siemens', expected)
            self.assertAlmostEqual(result['expected_value'], expected)
            self.assertAlmostEqual(result['zop'], 0)
            self.assertAlmostEqual(result['percentile'], 50)
            delta = 1.961 * (model['mse'] * (1 + model['covariance'][i][i])) ** 0.5
            self.assertAlmostEqual(result['upper_95pi'], expected + delta)
            self.assertAlmostEqual(result['lower_95pi'], expected - delta)

    def test_age_sex_scanner_grid_finite(self):
        for model in self.pack['models']:
            for age in (18, 28, 73, 94):
                for sex in ('Male', 'Female'):
                    for scanner in ('GE', 'Philips', 'Siemens'):
                        r = predict(model, self.pack, age, sex, 1500000, 1.5, scanner, 2.5)
                        self.assertTrue(np.isfinite(r['expected_value']))
                        self.assertLess(r['lower_95pi'], r['upper_95pi'])

    def test_label_blind_and_failure_gates(self):
        row = self.feature()
        original = evaluate_features(pd.DataFrame([row]), self.pack)
        self.assertEqual(original.iloc[0].calculation_status, 'calculated')
        changed = evaluate_features(pd.DataFrame([{**row, 'diagnosis': 'AD'}]), self.pack)
        self.assertEqual(original.iloc[0].expected_value, changed.iloc[0].expected_value)
        for mutation in ({'age': 17}, {'unit': 'cm'}, {'atlas_name': 'DKT'},
                         {'source_file': '/test/rh.aparc.stats'}, {'scanner_manufacturer': 'unknown'},
                         {'estimated_total_intracranial_volume': np.nan}, {'value_numeric': -1},
                         {'processing_software_version': None}, {'processing_software_version': '8.2.0'},
                         {'source_pipeline': 'CAT12'}):
            r = evaluate_features(pd.DataFrame([{**row, **mutation}]), self.pack)
            self.assertEqual(r.iloc[0].calculation_status, 'not_calculated', mutation)
        dup = evaluate_features(pd.DataFrame([row, row]), self.pack)
        self.assertTrue(dup.calculation_status.eq('not_calculated').all())

    def test_different_method_qualitative_only(self):
        result = evaluate_features(pd.DataFrame([self.feature()]), self.pack)
        refs = [dict(roi_name='superiortemporal', hemisphere='bilateral',
                     imaging_metric='cortical_thickness', evidence_note='Example test statement',
                     paper_code='TEST', atlas_name='another atlas', processing_pipeline='another tool')]
        links = qualitative_links(result, refs)
        self.assertEqual(len(links), 1)
        self.assertFalse(links.iloc[0].numeric_use)
        self.assertEqual(links.iloc[0].case_review_status, 'pending_human_review')
        refs[0]['hemisphere'] = 'rh'
        self.assertTrue(qualitative_links(result, refs).empty)


if __name__ == '__main__':
    unittest.main()
