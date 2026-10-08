import copy
import unittest

from report_interpretation import assessment, status_html
from zheng_exploratory import regional_candidate, render
import test_zheng_age_policy


class ReportInterpretationTests(unittest.TestCase):
    def setUp(self):
        self.comparison = test_zheng_age_policy.AgePolicyTest().assess(73)

    def test_adlike_is_retained_without_assigned_diagnosis(self):
        record = assessment(self.comparison)
        self.assertEqual(record['exploratory_candidates'], ['AD-like regional pattern'])
        self.assertIsNone(record['assigned_diagnosis'])
        self.assertIsNone(record['disease_probabilities'])
        self.assertIn('AD remains a candidate', render(self.comparison))

    def test_mixed_or_control_like_regions_do_not_trigger_ad_candidate(self):
        for count in range(4):
            result = copy.deepcopy(self.comparison)
            for index, row in enumerate(result['features']):
                row['closer_density'] = 'AD' if index < count else 'Control'
            self.assertFalse(regional_candidate(result))
            self.assertEqual(assessment(result)['exploratory_candidates'], [])
            self.assertNotIn('AD remains a candidate', render(result))

    def test_four_rows_must_be_four_distinct_required_regions(self):
        result = copy.deepcopy(self.comparison)
        result['features'][3] = copy.deepcopy(result['features'][0])
        self.assertFalse(regional_candidate(result))
        result['features'] = result['features'][:3]
        self.assertFalse(regional_candidate(result))

    def test_nonpositive_volume_is_not_candidate(self):
        for value in (0, -1, float('nan')):
            result = copy.deepcopy(self.comparison)
            result['features'][0]['observed'] = value
            self.assertFalse(regional_candidate(result))

    def test_expected_labels_cannot_override_feature_assessment(self):
        original = assessment(self.comparison)
        for group in ('AD', 'PD', 'Control'):
            result = dict(self.comparison, diagnosis=group, expected_label=group)
            self.assertEqual(assessment(result), original)

    def test_pd_scope_and_missing_data_do_not_assign_control_or_pd(self):
        for result in (None, dict(features=[])):
            record = assessment(result, 'PD')
            self.assertEqual(record['exploratory_candidates'], [])
            self.assertIsNone(record['assigned_diagnosis'])
        self.assertIn('Normal-range measurements do not', status_html())

    def test_reference_counts_are_not_patient_votes(self):
        rendered = render(self.comparison)
        self.assertNotIn('Favor AD', rendered)
        self.assertNotIn('Favor Control', rendered)
        self.assertIn('Higher density: AD reference', rendered)


if __name__ == '__main__':
    unittest.main()
