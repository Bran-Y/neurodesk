import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
from comparison_atlas import mapping_error
from report_quality import QC_FILES, read_qc, source_fingerprint
from segmentation_holds import POLICY, annotate_features, apply_normative_holds, hold_html, policies


class SegmentationHoldTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.result = dict(project_dir=self.root, fs_root=self.root / 'subjects')
        for name in QC_FILES:
            path = self.result['fs_root'] / 'case' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        self.record = dict(subject_id='case', status='active', scope='roi',
            roi_names=['Left-Amygdala', 'Right-Amygdala'], reason='QC hold: boundary unconfirmed.',
            source_fingerprint=source_fingerprint(self.result['fs_root'], 'case')[0])
        self.path = self.root / POLICY
        self.path.parent.mkdir(parents=True)
        self.save()
        self.features = pd.DataFrame([dict(subject_id='case', roi_name=roi,
            hemisphere='lh', imaging_metric='roi_volume', value_numeric=value)
            for roi, value in [('Left-Amygdala', 1200.), ('Left-Hippocampus', 4000.)]])

    def save(self):
        self.path.write_text(json.dumps(dict(schema_version=1, holds=[self.record])))

    def test_roi_hold_preserves_raw_and_other_regions(self):
        held = annotate_features(self.result, self.features)
        pd.testing.assert_frame_equal(held[self.features.columns], self.features)
        self.assertTrue(mapping_error(held.iloc[0]))
        self.assertFalse(mapping_error(held.iloc[1]))
        self.assertEqual(read_qc(self.result, 'case')['status'], 'pending_visual_review')

    def test_subject_hold_includes_unlocalized_extent(self):
        self.record['scope'] = 'subject'
        self.save()
        self.assertTrue(annotate_features(self.result, self.features).qc_hold_reason.ne('').all())

    def test_source_change_never_silently_releases_hold(self):
        (self.result['fs_root'] / 'case/mri/orig.mgz').write_bytes(b'changed')
        held = annotate_features(self.result, self.features)
        self.assertIn('Source changed', held.iloc[0].qc_hold_reason)

    def test_missing_policy_no_effect(self):
        self.path.unlink()
        pd.testing.assert_frame_equal(annotate_features(self.result, self.features), self.features)

    def test_normative_derived_results_cleared_raw_preserved(self):
        held = annotate_features(self.result, self.features)
        norms = self.features.rename(columns={'value_numeric': 'observed_value'}).assign(
            calculation_status='calculated', range_status='below_95pi', exclusion_reason='',
            expected_value=1500., zop=-2., lower_95pi=1300., upper_95pi=1700.)
        actual = apply_normative_holds(held, norms)
        self.assertEqual(actual.iloc[0].observed_value, 1200.)
        self.assertEqual(actual.iloc[0].range_status, 'not_assessed')
        self.assertTrue(pd.isna(actual.iloc[0].zop))
        pd.testing.assert_series_equal(actual.loc[1, norms.columns], norms.iloc[1])
        self.result['comparison_features'] = held
        self.assertIn('not a confirmed segmentation failure', hold_html(self.result, 'case'))

    def test_release_without_accepted_review_rejected(self):
        self.record.update(status='resolved', resolution_record={'source_fingerprint': self.record['source_fingerprint']})
        self.save()
        with self.assertRaises(ValueError):
            policies(self.result)

    def test_export_schema_when_all_models_are_skipped(self):
        from segmentation_holds import DERIVED
        self.record['scope'] = 'subject'
        self.save()
        held = annotate_features(self.result, self.features)
        norms = self.features.rename(columns={'value_numeric': 'observed_value'}).assign(
            calculation_status='not_calculated', exclusion_reason='QC hold')
        out = apply_normative_holds(held, norms)
        self.assertTrue(set(DERIVED).issubset(out.columns))
        self.assertTrue(out[list(DERIVED)].isna().all().all())

    def test_additional_pd_group_means_exclude_held_volume(self):
        from pd_reviewed_comparison import compare
        features = self.features.assign(atlas_name='FreeSurfer aseg', unit='mm3', processing_software_version='5.3.0')
        self.result['features'] = annotate_features(self.result, features)
        folder = self.root / 'workflow_sources/Disease/PD'
        folder.mkdir(parents=True)
        (folder / 'reviewed_pd_quantitative_tables.json').write_text(json.dumps({'sources': [
            dict(paper='fixture', doi='10.fixture', processing_version='5.3', source_url='fixture', records=[
                dict(evidence_id='e', source_table='1', source_row='1', record_kind='baseline_volume',
                     structure='Amygdala', hemisphere='lh', mean=1.3, sd=.1, unit='ml')])]}))
        approval = self.root / 'workflow_sources/paper_reading_reviews'
        approval.mkdir(parents=True)
        (approval / 'pd_paper_review_approvals.json').write_text(json.dumps({'papers': [
            dict(doi='10.fixture', human_review_status='accepted', data_use_status='user_approved_research_use')]}))
        row = compare(self.result, 'case')[0]
        self.assertEqual(row['comparison_status'], 'not_comparable')
        self.assertIsNone(row['measured'])
        self.assertIsNone(row['difference_from_group_mean'])

    def test_enigma_withholds_even_if_old_normative_result_was_calculated(self):
        from pd_evidence import compare_records
        source = Path(__file__).parent / 'workflow_sources/Disease/PD/enigma_pd_group_statistics.json'
        ref = next(r for r in json.loads(source.read_text())['records']
                   if r['source_structure'] == 'L_entorhinal' and r['imaging_metric'] == 'cortical_thickness')
        patient = dict(ref, subject_id='case', value_numeric=2.0,
                       qc_hold_reason='QC hold: boundary unconfirmed.')
        normative = dict(patient, calculation_status='calculated', range_status='below_95pi')
        output = compare_records([patient], [normative], [ref], 'case')[0]
        self.assertEqual(output['match_status'], 'unavailable')
        self.assertEqual(output['normative_status'], 'not_calculated')
        self.assertIsNone(output['measured'])
        self.assertIn('QC hold:', output['context'])
        self.assertNotIn('in the published group-effect direction', output['context'])


if __name__ == '__main__':
    unittest.main()
