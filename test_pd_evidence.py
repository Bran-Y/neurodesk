import unittest
import json
from pathlib import Path
from pd_evidence import direction_context
from pd_evidence import nominal_significance, reported_direction_context


class DirectionTests(unittest.TestCase):
    def test_reported_p_bounds_are_not_guessed(self):
        for value in ('0.173', '0.529', '0.764', '0.05', '>0.05'):
            self.assertIs(nominal_significance(value), False)
        for value in ('0.01', '<0.001', '<0.05', '1e-5'):
            self.assertIs(nominal_significance(value), True)
        for value in (None, 'NaN', '1.5', '<0.1', '>0.01', '<=0.05'):
            self.assertIsNone(nominal_significance(value))

    def test_nonsignificant_sign_matches_are_not_pd_support(self):
        for effect, state, p in ((.043, 'above_95pi', '0.173'), (-.02, 'below_95pi', '0.529')):
            text = reported_direction_context(state, effect, p)
            self.assertIn('not nominally significant', text)
            self.assertIn('same sign', text)
            self.assertIn('Not disease support', text)
            self.assertNotIn('in the published group-effect direction', text)
        self.assertIn('not nominally significant', reported_direction_context('above_95pi', -.011, '0.764'))
        self.assertIn('neither confirms nor excludes', reported_direction_context('within_95pi', -.02, '0.529'))
        self.assertIn('corrected significance not established', reported_direction_context('above_95pi', -.167, '<0.001'))

    def test_direction_not_diagnosis(self):
        self.assertIn('published group-effect direction', direction_context('below_95pi', -.2))
        self.assertIn('opposite', direction_context('above_95pi', -.2))
        self.assertIn('neither confirms nor excludes', direction_context('within_95pi', -.2))

    def test_missing_never_normal(self):
        for status in (None, 'not_calculated', float('nan')):
            self.assertEqual(direction_context(status, -.2), 'Not directionally assessed')
        self.assertEqual(direction_context('below_95pi', float('nan')), 'Not directionally assessed')

    def test_real_data_and_mapping_guards(self):
        from pd_evidence import compare_records
        refs = json.loads((Path(__file__).parent / 'workflow_sources/Disease/PD/enigma_pd_group_statistics.json').read_text())['records']
        self.assertEqual(len(refs), 152)
        self.assertEqual(len({r['evidence_id'] for r in refs}), 152)
        r = next(r for r in refs if r['source_structure'] == 'L_entorhinal' and r['imaging_metric'] == 'cortical_thickness')
        patient = dict(r, subject_id='test', value_numeric=2.4)
        norm = dict(patient, calculation_status='calculated', range_status='within_95pi')
        out = compare_records([patient], [norm], [r], 'test')[0]
        self.assertEqual(out['match_status'], 'matched_for_context')
        self.assertIn('neither confirms nor excludes', out['context'])
        self.assertEqual(compare_records([patient, patient], [norm], [r], 'test')[0]['match_status'], 'unavailable')
        self.assertEqual(compare_records([dict(patient, unit='cm')], [norm], [r], 'test')[0]['match_status'], 'unavailable')
        self.assertEqual(compare_records([dict(patient, processing_software_version='8.2')], [norm], [r], 'test')[0]['match_status'], 'unavailable')
        self.assertEqual(compare_records([patient], [], [r], 'test')[0]['context'], 'Not directionally assessed')
        norm.update(expected_value=2.5, lower_95pi=2.1, upper_95pi=2.9, zop=-.5)
        self.assertEqual(compare_records([patient], [norm], [r], 'test')[0]['expected_value'], 2.5)
        self.assertIsNone(compare_records([patient, patient], [norm], [r], 'test')[0]['expected_value'])
        self.assertIsNone(compare_records([patient], [norm, norm], [r], 'test')[0]['expected_value'])


if __name__ == '__main__':
    unittest.main()
