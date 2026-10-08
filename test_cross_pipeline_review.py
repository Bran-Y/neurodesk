import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from processing_compatibility import same_version, all_versions_match
from cross_pipeline_review import profiles, patient_metadata, subject_audit, render, publish
from reference_range_overlap import compare_ranges


class ProcessingReviewTests(unittest.TestCase):
    def test_aliases_match_without_erasing_patch_version(self):
        self.assertTrue(same_version('5.3', '5.3.0'))
        self.assertFalse(same_version('5.3.1', '5.3.0'))
        self.assertFalse(same_version('8.2.0', '5.3.0'))

    def test_unknown_is_not_compatible(self):
        for value in (None, '', 'unknown', 'not reported', float('nan'), '5.3 (modified)'):
            self.assertFalse(same_version(value, '5.3.0'), value)
            self.assertFalse(same_version(value, value), value)

    def test_empty_and_partially_missing_versions_fail(self):
        for values in ([], [None], ['5.3.0', None], ['5.3.0', '8.2.0']):
            self.assertFalse(all_versions_match(values, '5.3'))
        self.assertTrue(all_versions_match(['5.3', '5.3.0'], '5.3'))

    def result(self, **mutations):
        row = dict(subject_id='test', source_pipeline='FreeSurfer', processing_software_version='5.3.0',
                   comparison_atlas_code='freesurfer_aseg', hemisphere='lh', unit='mm3', statistic_type='raw')
        return dict(comparison_features=pd.DataFrame([{**row, **mutations}]))

    def test_native_version_does_not_approve_cross_pipeline_calibration(self):
        result = self.result()
        self.assertTrue(patient_metadata(result, 'test')['all_recorded_versions_fs53'])
        table = subject_audit(result, 'test')
        self.assertTrue(table.calibration_status.eq('not_validated').all())
        self.assertFalse(table.calibrated_numeric_transfer.any())

    def test_patient_unknown_metadata_remains_visible(self):
        result = self.result(processing_software_version=None, unit=None)
        metadata = patient_metadata(result, 'test')
        self.assertFalse(metadata['all_recorded_versions_fs53'])
        self.assertEqual(metadata['unit'], 'Not recorded')
        self.assertIn('Missing or mixed processing versions', render(result, 'test'))

    def test_empty_subject_is_not_passed(self):
        with self.assertRaises(ValueError):
            patient_metadata(self.result(), 'missing')

    def test_pd_focus_does_not_add_ad_sources(self):
        result = self.result()
        result['reference_focus'] = 'PD'
        table = subject_audit(result, 'test')
        self.assertEqual(len(table), 4)
        self.assertNotIn('10.1371/journal.pone.0279574', set(table.doi))

    def test_explicit_source_scope_respected(self):
        result = self.result()
        result['papers'] = pd.DataFrame([dict(doi='10.1159/000084560')])
        self.assertEqual(list(subject_audit(result, 'test').source_code), ['DIS-008'])

    def test_measurement_definition_differences_recorded(self):
        table = profiles().set_index('source_code')
        self.assertIn('normalized', table.loc['QREF-003', 'measurement_definition'])
        self.assertIn('whole-brain', table.loc['QREF-002', 'measurement_definition'])
        self.assertIn('unreported', table.loc['QREF-001', 'reference_method'])
        self.assertEqual(len(table), 15)

    def test_range_gate_checks_software_version_not_just_atlas(self):
        # Isolate numeric method gates from the already-tested atlas registry translation.
        patient = dict(subject_id='test', comparison_registry='test', age=65, sex='Female',
                       value_numeric=100, unit='mm3', atlas_name='aseg', atlas_version='identity',
                       source_pipeline='FreeSurfer', statistic_type='raw', processing_software_version='5.3.0',
                       atlas_translation_review_status='reviewed_quantitative_ready', mapping_relation='exact')
        reference = dict(doi='test', diagnosis='AD', source_location='Table 1', range_lower=80, range_upper=120,
                         range_type='individual_prediction_interval', range_source='Test model', range_coverage=.95,
                         reference_age_min=18, reference_age_max=90, reference_sex='all', unit='mm3',
                         atlas_name='aseg', atlas_version='identity', processing_pipeline='FreeSurfer',
                         normalization_method='raw', processing_software_version='5.3', human_review_status='accepted',
                         reviewed_by='fixture', reviewed_at='test', comparison_compatible=True,
                         atlas_translation_review_status='reviewed_quantitative_ready', mapping_relation='exact')
        with patch('reference_range_overlap.translate_records', side_effect=lambda rows, registry: rows), \
                patch('reference_range_overlap.mapping_error', return_value=''), \
                patch('reference_range_overlap.key', return_value=('hippocampus', 'lh', 'roi_volume')):
            for value, expected in [('5.3', True), ('8.2.0', False), (None, False)]:
                _, audit = compare_ranges(pd.DataFrame([patient]),
                                          [{**reference, 'processing_software_version': value}], 'test')
                self.assertEqual(bool(audit.iloc[0].eligible), expected)
                if not expected:
                    self.assertIn('processing_software_version_incompatible_or_missing', audit.iloc[0].exclusion_reason)

    def test_publish_preserves_incomplete_and_no_calibration_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            final = root / 'outputs/final_reports_20261004'
            final.mkdir(parents=True)
            report = 'outputs/test/concise_reports/test_concise_report.html'
            out = root / 'outputs/test/concise_reports'
            out.mkdir(parents=True)
            subject_audit(self.result(), 'test').to_csv(out / 'test_cross_pipeline_review.csv', index=False)
            (final / 'verification.json').write_text(json.dumps([
                dict(subject_id='test', report=report), dict(subject_id='incomplete', report=None)]))
            data = publish(root)
            self.assertFalse(data['cross_pipeline_calibration_complete'])
            self.assertFalse(data['human_segmentation_qc_modified'])
            self.assertEqual(data['patients'][1]['exported_method_rows'], 0)
            page = (root / 'outputs/cross_pipeline_review_20261005/CROSS_PIPELINE_REVIEW.html').read_text()
            self.assertIn('held-out', page)
            self.assertNotIn('pending_review', page)


if __name__ == '__main__':
    unittest.main()
