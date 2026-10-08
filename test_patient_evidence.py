import unittest
from unittest.mock import patch
import pandas as pd
from patient_evidence_ledger import ledger


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.p = dict(subject_id='S', roi_name='hippocampus', hemisphere='lh',
            imaging_metric='roi_volume', unit='mm3', value_numeric=100, age=70,
            atlas_name='aseg', processing_software_version='5.3.0', normalization_method='raw')
        self.r = dict(self.p, evidence_id='E', paper_id='P', source_title='Test',
            manual_review_status='accepted', human_review_status='accepted',
            comparison_compatible=True, roi_boundary_verified=True,
            reference_age_min=60, reference_age_max=80, reference_interval_type='individual_95pi',
            interval_applicability_verified=True, reference_lower=100, reference_upper=200)

    def run_case(self, ref=None, patient=None):
        return ledger({'features': pd.DataFrame([patient or self.p]),
            'literature_audit': {'evidence': pd.DataFrame([ref or self.r])}}, 'S').iloc[0]

    def test_bounds_and_no_probability(self):
        for value in (100, 200):
            row = self.run_case(patient=dict(self.p, value_numeric=value))
            self.assertTrue(row.within_individual_range)
            self.assertIsNone(row.diagnostic_probability)

    def test_rejected_missing_and_mismatched(self):
        for changes in ({'human_review_status': 'rejected'}, {'reference_interval_type': 'group_ci'},
                        {'reference_lower': None}, {'hemisphere': 'rh'}, {'unit': 'cm3'},
                        {'interval_applicability_verified': False}):
            row = self.run_case(ref=dict(self.r, **changes))
            self.assertIsNone(row.within_individual_range)
            self.assertNotEqual(row.use_status, 'individual_range_comparison')

    def test_label_blind(self):
        a = self.run_case(patient=dict(self.p, diagnosis='AD'))
        b = self.run_case(patient=dict(self.p, diagnosis='Control'))
        pd.testing.assert_series_equal(a, b)

    def test_authorized_distribution_comparison_is_recorded_not_a_normal_range(self):
        from comparison_atlas import translate_records, feature_key
        ref = dict(self.r, doi='test-doi', diagnosis='AD', unit='mm3',
                   reference_interval_type='group_distribution')
        translated = translate_records([ref])[0]
        computed = {('test-doi', *feature_key(translated)): dict(unit='mm3', observed=100,
            AD_mean=120, AD_sd=10, AD_z=-2, log_density_ratio_AD_Control=1,
            closer_density='AD', age_applicable=False)}
        with patch('patient_evidence_ledger.exploratory_results', return_value=computed):
            row = self.run_case(ref=ref)
            self.assertEqual(row.use_status, 'exploratory_distribution_comparison')
            self.assertTrue(row.comparison_performed)
            self.assertEqual(row.observed_minus_mean, -20)
            self.assertEqual(row.exploratory_z, -2)
            self.assertFalse(row.age_applicable)
            self.assertIsNone(row.within_individual_range)
            self.assertIsNone(row.diagnostic_probability)
            rejected = self.run_case(ref=dict(ref, human_review_status='rejected'))
            self.assertFalse(rejected.comparison_performed)


if __name__ == '__main__':
    unittest.main()
