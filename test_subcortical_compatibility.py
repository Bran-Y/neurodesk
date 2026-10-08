"""Portable regression checks; not native Excel or clinical validation."""
import itertools
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from comparison_atlas import feature_key, mapping_error, translate_records
from potvin_subcortical import extract, predict, preview, augment_normative

ROOT = Path(__file__).parent
WORKBOOK = ROOT / 'workflow_sources/external_validators/potvin_subcortical/mmc2.xlsm'


class SubcorticalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = extract(WORKBOOK)

    def patient(self, **changes):
        return dict(dict(subject_id='synthetic', roi_name='Left-Hippocampus',
                         hemisphere='lh', atlas_name='FreeSurfer aseg',
                         imaging_metric='roi_volume', unit='mm3', value_numeric=4000.,
                         age=60., sex='Male', scanner_manufacturer='Siemens',
                         scanner_field_strength=3., estimated_total_intracranial_volume=1500000.,
                         source_file='synthetic/stats/aseg.stats',
                         processing_software_version='5.3.0', atlas_version='5.3.0'), **changes)

    def preview_row(self, rows):
        result = dict(project_dir=ROOT, features=pd.DataFrame(rows))
        return preview(result, 'synthetic').iloc[0]

    def test_reference_has_independent_formula_concordance(self):
        row = self.preview_row([self.patient()])
        self.assertEqual(row.status, 'calculated')
        self.assertEqual(row.range_status, 'within_95pi')
        self.assertEqual(row.validation_status, 'calc_formula_concordance_passed')
        self.assertLess(row.lower_95pi, row.expected)
        self.assertGreater(row.upper_95pi, row.expected)

    def test_version_unit_measurement_and_identity_guards(self):
        for changes in ({'processing_software_version': '8.2'}, {'atlas_version': '8.2'},
                        {'processing_software_version': None, 'atlas_version': None},
                        {'value_numeric': float('nan')}, {'value_numeric': -1},
                        {'unit': 'cm3'}, {'hemisphere': 'rh'}, {'source_file': 'lh.aparc.stats'},
                        {'age': None}, {'estimated_total_intracranial_volume': None}):
            with self.subTest(changes=changes):
                row = self.preview_row([self.patient(**changes)])
                self.assertEqual(row.status, 'unavailable')
                self.assertIsNone(row.expected)
        self.assertEqual(self.preview_row([self.patient(), self.patient()]).status, 'unavailable')

    def test_fixture_capture_and_source_integrity(self):
        from verify_mmc2_fixture import verify, RELATIVE_DIR
        result = verify(ROOT)
        self.assertEqual(result['cases'], 146)
        self.assertEqual(result['numeric_comparisons'], 1752)
        self.assertLess(result['max_absolute_error_mm3'], 1e-7)
        self.assertFalse(result['clinically_validated'])
        self.assertFalse(result['native_excel_validated'])
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / RELATIVE_DIR / 'calc_validation_fixture.json'
            fixture.parent.mkdir(parents=True)
            fixture.write_bytes((ROOT / RELATIVE_DIR / fixture.name).read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'fixture revision'):
                verify(directory)

    def test_mutated_coefficients_fail_fixture_replay(self):
        import copy
        from verify_mmc2_fixture import verify
        models = copy.deepcopy(self.models)
        models[0]['beta'][0] += 1
        with self.assertRaisesRegex(ValueError, 'concordance failed'):
            verify(ROOT, models)
        with self.assertRaisesRegex(ValueError, 'Incomplete mmc2 model'):
            verify(ROOT, models[:1])

    def test_bounds_inclusive_and_main_counts_no_new_rows(self):
        from mmc_normative_workflow import evaluate_features
        pack = dict(models=[], source_title='cortical', doi='cortical', source_sha256='cortical')
        base = self.patient()
        _, lower, upper = predict(self.models[0], base)
        for value, status in ((lower, 'within_95pi'), (upper, 'within_95pi'),
                              (lower-1e-5, 'below_95pi'), (upper+1e-5, 'above_95pi')):
            frame = pd.DataFrame([self.patient(value_numeric=value)])
            result = dict(project_dir=ROOT, features=frame)
            out = augment_normative(result, evaluate_features(frame, pack))
            self.assertEqual(len(out), 1)
            row = out.iloc[0]
            self.assertEqual(row.range_status, status)
            self.assertEqual(row.calculation_status, 'calculated')
            self.assertEqual(row.source_doi, '10.1016/j.neuroimage.2016.05.016')
        with patch('verify_mmc2_fixture.verify', side_effect=ValueError('fixture failure')):
            out = augment_normative(result, evaluate_features(frame, pack))
            self.assertEqual(out.iloc[0].calculation_status, 'not_calculated')
            self.assertIn('fixture failure', out.iloc[0].exclusion_reason)

    def test_ai_attributes_subcortical_to_2016_not_cortical_source(self):
        from ai_evidence_assistant import build_payload
        from mmc_normative_workflow import evaluate_features
        frame = pd.DataFrame([self.patient()])
        result = dict(project_dir=ROOT, features=frame, reference_focus='PD')
        result['normative'] = augment_normative(result, evaluate_features(frame,
            dict(models=[], source_title='cortical', doi='cortical', source_sha256='cortical')))
        with patch('pd_evidence.compare_result', return_value=[]):
            payload = build_payload(result, 'synthetic')
        self.assertEqual(payload['evidence'][0]['source'], 'Potvin_subcortical')
        self.assertEqual(payload['sources']['Potvin_subcortical'],
                         'https://doi.org/10.1016/j.neuroimage.2016.05.016')
        self.assertNotIn('Potvin', payload['sources'])

    def test_saved_ai_audit_selects_evidence_hash_not_last_or_only_prompt(self):
        import ai_evidence_assistant as ai
        from verify_pd_cases import current_request
        payload = {'evidence': ['new synthetic evidence']}
        def record(data, **changes):
            return dict(dict(local_subject_id='synthetic', prompt_version=ai.PROMPT_VERSION,
                payload_sha256=ai.payload_hash(data), evidence_payload=data, status='complete'), **changes)
        old = record({'evidence': ['old synthetic evidence']})
        new = record(payload)
        self.assertIs(current_request([new, old], 'synthetic', payload), new)
        with self.assertRaises(ValueError):
            current_request([old], 'synthetic', payload)
        with self.assertRaises(ValueError):
            current_request([new, new], 'synthetic', payload)
        with self.assertRaises(ValueError):
            current_request([record(payload, status='pending')], 'synthetic', payload)

    def test_unknown_workbook_revision_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'changed.xlsm'
            path.write_bytes(WORKBOOK.read_bytes() + b'changed')
            with self.assertRaisesRegex(ValueError, 'Unverified mmc2'):
                extract(path)

    def test_finite_predictions_across_supported_covariates(self):
        # A numerical stability check only; it cannot validate clinical applicability.
        for age, sex, field, scanner, etiv in itertools.product(
                (18, 60, 94), ('Male', 'Female'), (1.5, 3),
                ('Siemens', 'GE', 'Philips'), (1200000, 1800000)):
            patient = self.patient(age=age, sex=sex, scanner_field_strength=field,
                                   scanner_manufacturer=scanner,
                                   estimated_total_intracranial_volume=etiv)
            for model in self.models:
                mean, low, high = predict(model, patient)
                self.assertTrue(all(math.isfinite(v) for v in (mean, low, high)))
                self.assertLess(low, mean)
                self.assertLess(mean, high)

    def test_scalar_regression_matches_matrix_prediction(self):
        # This independently checks dot-product arithmetic, not workbook recalculation.
        from scipy.stats import t
        for model in self.models:
            values = {'b0': 1., 'agec': 60-47.5634617, 'sexq': 1.,
                      'tivc': 1500000-1521907.28}
            values['agec2'] = values['agec'] ** 2
            values['agec3'] = values['agec'] ** 3
            values['tivc2'] = values['tivc'] ** 2
            values['tivc3'] = values['tivc'] ** 3
            values['agec_x_sexq'] = values['agec']
            x = [values.get(term.lower(), 0.) for term in model['terms']]
            mean = sum(a*b for a, b in zip(x, model['beta']))
            leverage = sum(x[i]*model['covariance'][i][j]*x[j]
                           for i in range(len(x)) for j in range(len(x)))
            half = t.ppf(.975, model['critical_df']) * math.sqrt(model['mse']*(1+leverage))
            for actual, expected in zip(predict(model, self.patient()), (mean, mean-half, mean+half)):
                self.assertAlmostEqual(actual, expected, places=8)


class ThalamusTests(unittest.TestCase):
    def test_native_proper_labels_are_distinct_from_legacy_labels(self):
        for side, prefix in (('lh', 'Left'), ('rh', 'Right')):
            records = translate_records([dict(roi_name=prefix+'-Thalamus'+suffix,
                hemisphere=side, atlas_name='FreeSurfer aseg', imaging_metric='roi_volume')
                for suffix in ('-Proper', '')])
            self.assertFalse(any(mapping_error(row) for row in records))
            self.assertNotEqual(feature_key(records[0]), feature_key(records[1]))
            self.assertEqual(records[0]['standard_roi_name'], 'thalamus proper')

    def test_all_pd_reference_features_map_without_creating_normal_ranges(self):
        import json
        from pd_evidence import compare_records
        refs = json.loads((ROOT/'workflow_sources/Disease/PD/enigma_pd_group_statistics.json').read_text())['records']
        self.assertEqual(sum(not mapping_error(r) for r in translate_records(refs)), 152)
        for ref in refs:
            if 'Thalamus-Proper' not in ref['roi_name']:
                continue
            patient = dict(ref, subject_id='synthetic', value_numeric=6000., processing_software_version='5.3.0')
            row = compare_records([patient], [], [ref], 'synthetic')[0]
            self.assertEqual(row['match_status'], 'matched_for_context')
            self.assertEqual(row['context'], 'Not directionally assessed')


if __name__ == '__main__':
    unittest.main()
