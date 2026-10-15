import unittest
from unittest.mock import patch

import zheng_exploratory as zheng


class AgePolicyTest(unittest.TestCase):
    def assess(self, age):
        features, refs = [], []
        for roi in ('hippocampus', 'amygdala'):
            for side in ('lh', 'rh'):
                base = dict(roi=roi, hemisphere=side, metric='roi_volume', unit='mm3',
                            comparison_atlas_code='aseg',
                            atlas_translation_review_status='reviewed_quantitative_ready')
                features.append(dict(base, subject_id='case', age=age, value_numeric=10,
                                     statistic_type='raw_measure'))
                for group, mean in [('AD', 10), ('Control', 20)]:
                    refs.append(dict(base, doi='10.1371/journal.pone.0279574', diagnosis=group,
                                     human_review_status='accepted', reference_age_min=60,
                                     reference_age_max=90, mean=mean, standard_deviation=2, sample_size=100))
        with patch.object(zheng, 'translate_records', side_effect=lambda rows, registry: rows), \
             patch.object(zheng, 'mapping_error', return_value=None), \
             patch.object(zheng, 'feature_key', side_effect=lambda r: (r['roi'], r['hemisphere'], r['metric'])):
            return zheng.compare(features, refs, 'case')

    def test_out_of_range_age_keeps_comparison_and_candidate(self):
        young, older = self.assess(28), self.assess(73)
        self.assertEqual(young['families'], older['families'])
        self.assertEqual(len(young['features']), 4)
        self.assertEqual(young['exclusions'], [])
        self.assertTrue(any('Assessment continues' in w for w in young['warnings']))
        self.assertFalse(older['warnings'])
        for result in (young, older):
            self.assertIn('AD remains a candidate', zheng.render(result))
            self.assertIsNone(result['disease_prediction'])

    def test_reference_age_boundaries_are_inclusive(self):
        for age in (60, 90):
            self.assertTrue(all(r['age_applicable'] for r in self.assess(age)['features']))


if __name__ == '__main__':
    unittest.main()
