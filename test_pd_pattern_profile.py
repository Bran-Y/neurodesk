import copy
import unittest
from pd_pattern_profile import profile, render
from possible_disease_interpretation import summarize


def row(**kwargs):
    return dict(dict(doi='10.1002/mds.28706', comparison_group='whole_sample',
                     match_status='matched_for_context', direction_eligible=True,
                     review_status='pending_human_review', mapping_method='same_native_atlas_label_alignment',
                     normative_status='within_95pi', measured=2.4, expected_value=2.5,
                     pd_minus_control_cohen_d=-.2, p_as_reported='<0.001', context='Within normative PI',
                     standard_roi_name='precentral', hemisphere='lh', metric='cortical_thickness', unit='mm'), **kwargs)


class PatternTests(unittest.TestCase):
    def test_normal_range_match_is_described_but_not_positive_classification(self):
        summary = summarize(pd_rows=[row()], scope='PD')
        self.assertEqual(len(summary['pd']['directional_profile']['aligned']), 1)
        self.assertFalse(summary['pd']['pattern_present'])
        self.assertIsNone(summary['assigned_diagnosis'])
        self.assertIn('not a PD classification', summary['conclusion'])
        self.assertIn('1/1', render(summary['pd']['directional_profile']))

    def test_opposite_and_equal_not_counted_as_matches(self):
        result = profile([row(measured=2.6), row(hemisphere='rh', measured=2.5)])
        self.assertEqual(result['assessed'], 2)
        self.assertEqual(len(result['aligned']), 0)
        self.assertEqual(len(result['opposed']), 1)
        self.assertEqual(len(result['at_expected']), 1)

    def test_guards_not_relaxed(self):
        for changes in ({'p_as_reported': '0.529'}, {'match_status': 'unavailable'},
                        {'direction_eligible': False}, {'comparison_group': 'HY1'},
                        {'mapping_method': 'not_comparable'}, {'doi': 'other'},
                        {'expected_value': None}, {'expected_value': float('nan')},
                        {'normative_status': 'not_calculated'}, {'measured': 0},
                        {'review_status': 'rejected'}, {'pd_minus_control_cohen_d': 0}):
            with self.subTest(changes=changes):
                self.assertEqual(profile([row(**changes)])['assessed'], 0)

    def test_duplicates_withheld_and_inputs_unchanged(self):
        rows = [row(), row()]
        before = copy.deepcopy(rows)
        result = profile(rows)
        self.assertEqual(result['assessed'], 0)
        self.assertEqual(result['excluded'], 2)
        self.assertEqual(rows, before)

    def test_known_cohort_never_changes_evidence(self):
        self.assertEqual(profile([row(recorded_research_group='PD')])['assessed'],
                         profile([row(recorded_research_group='Control')])['assessed'])
        a = summarize(pd_rows=[row(recorded_research_group='PD')], scope='PD')
        b = summarize(pd_rows=[row(recorded_research_group='Control')], scope='PD')
        self.assertEqual(a['pd']['pattern_present'], b['pd']['pattern_present'])
        self.assertFalse(a['known_diagnosis_used_as_input'])

    def test_output_escape_and_no_probability(self):
        result = profile([row(standard_roi_name='<script>')])
        self.assertIn('&lt;script&gt;', render(result))
        self.assertNotIn('<script>', render(result))
        self.assertIsNone(result['disease_probability'])
        self.assertIsNone(result['classification_threshold'])


if __name__ == '__main__':
    unittest.main()
