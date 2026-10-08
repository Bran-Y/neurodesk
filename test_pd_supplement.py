import json
from pathlib import Path
import unittest
from unittest.mock import patch
import pandas as pd

from pd_evidence import compare_records, compare_stage_result, render_pd, stage_context_payload
from ai_evidence_assistant import build_payload, candidate_context_direction, outbound_payload, serialise

ROOT = Path(__file__).parent
DATA = ROOT / 'workflow_sources/Disease/PD'


class SupplementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.whole = json.loads((DATA/'enigma_pd_group_statistics.json').read_text())['records']
        cls.stage = json.loads((DATA/'enigma_pd_stage_statistics.json').read_text())['records']

    def example(self):
        ref = next(r for r in self.whole if r['source_structure'] == 'Lhippo')
        patient = dict(ref, subject_id='synthetic', value_numeric=2900, age=65, sex='Male')
        norm = dict(patient, calculation_status='calculated', range_status='below_95pi')
        return patient, norm

    def test_original_coefficient_scale_and_sample_counts(self):
        ref = next(r for r in self.whole if r['source_structure'] == 'Lamyg')
        self.assertEqual((ref['effect_size'], ref['regression_coefficient']), (-0.130, -33.64))
        self.assertEqual((ref['n_patients'], ref['n_controls']), (2284, 1158))
        self.assertEqual(ref['regression_ci_target'], 'adjusted_group_difference_b')
        ref = next(r for r in self.whole if r['source_structure'] == 'Rpal')
        self.assertEqual(ref['regression_standard_error'], 8.69)
        self.assertEqual(ref['raw_columns']['se_icv'], '8,69')

    def test_primary_pdf_corrections_preserve_raw_source_history(self):
        from resolve_enigma_sources import CORRECTIONS
        self.assertEqual(sum(not r['direction_eligible'] for r in self.whole), 0)
        for eid, (field, old, value, page) in CORRECTIONS.items():
            ref = next(r for r in self.whole if r['evidence_id'] == eid)
            self.assertEqual(ref[field], value)
            self.assertEqual(ref['supplement_discrepancies'][field]['existing'], old)
            self.assertEqual(ref['primary_source_resolution']['status'], 'resolved_to_primary_pdf')
            self.assertFalse(ref['primary_source_resolution']['human_approval_inferred'])

    def test_unresolved_source_is_still_withheld(self):
        ref = dict(next(r for r in self.whole if r['source_structure'] == 'R_postcentral'),
                   direction_eligible=False)
        patient = dict(ref, subject_id='synthetic', value_numeric=1000)
        norm = dict(patient, calculation_status='calculated', range_status='below_95pi')
        row = compare_records([patient], [norm], [ref], 'synthetic')[0]
        self.assertEqual(row['match_status'], 'matched_for_context')
        self.assertIn('withheld', row['context'])
        self.assertIsNone(candidate_context_direction(dict(row, source='ENIGMA_PD',
                            kind='group_effect_context', comparable=True), 'PD'))

    def test_hy_context_does_not_assign_stage_or_duplicate_primary_rows(self):
        patient, norm = self.example()
        result = dict(project_dir=ROOT, normative=pd.DataFrame([norm]))
        with patch('comparison_atlas.comparison_features', return_value=pd.DataFrame([patient])):
            rows = compare_stage_result(result, 'synthetic')
            context = stage_context_payload(result, 'synthetic')
            report = render_pd(result, 'synthetic')
            payload = build_payload(result | {'reference_focus': 'PD'}, 'synthetic')
        self.assertEqual(len(rows), 608)
        self.assertEqual(context['patient_stage'], 'not_assigned')
        self.assertEqual(len(context['comparisons']), 4)
        hip = {r['comparison_group']: r for r in rows if r['source_structure'] == 'Lhippo'}
        self.assertEqual(hip['HY1']['pd_minus_control_cohen_d'], .069)
        self.assertEqual(hip['HY3']['pd_minus_control_cohen_d'], -.240)
        self.assertIn('opposite', hip['HY1']['context'])
        self.assertIn('published group-effect direction', hip['HY3']['context'])
        self.assertIn('S4k', report)
        self.assertEqual(sum(r['source'] == 'ENIGMA_PD' for r in payload['evidence']), 152)
        self.assertEqual(payload['pd_stage_context']['reference_rows'], 608)
        self.assertEqual(outbound_payload(payload)['pd_stage_context'], payload['pd_stage_context'])
        self.assertNotIn('synthetic', serialise(outbound_payload(payload)))

    def test_unknown_normative_status_is_not_directional_support(self):
        patient, norm = self.example()
        refs = [r for r in self.stage if r['source_structure'] == 'Lhippo']
        rows = compare_records([patient], [], refs, 'synthetic')
        self.assertTrue(all(r['context'] == 'Not directionally assessed' for r in rows))

    def test_conflicting_summary_sign_is_withheld(self):
        ref = next(r for r in self.stage if r['source_structure'] == 'LLatVent'
                   and r['comparison_group'] == 'HY4-5')
        self.assertEqual(ref['effect_size'], .357)
        self.assertFalse(ref['direction_eligible'])
        self.assertIn('S3c', ref['source_warning'])


if __name__ == '__main__':
    unittest.main()
