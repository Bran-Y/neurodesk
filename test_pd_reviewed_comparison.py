import json
import hashlib
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from pd_reviewed_comparison import compare, coverage
from segmentation_viewer import surface_slice_segments


class ReviewedComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.result = dict(project_dir=root, features=pd.DataFrame([dict(subject_id='TEST',
            roi_name='Left-Hippocampus', hemisphere='lh', imaging_metric='roi_volume',
            atlas_name='FreeSurfer aseg', value_numeric=4200, unit='mm3', processing_software_version='5.3.0')]))
        store = root / 'workflow_sources/Disease/PD'
        store.mkdir(parents=True)
        review = root / 'workflow_sources/paper_reading_reviews'
        review.mkdir()
        (review / 'pd_paper_review_approvals.json').write_text(json.dumps(dict(papers=[dict(doi='test',
            human_review_status='accepted', data_use_status='user_approved_research_use')])))
        records = [dict(evidence_id='B', source_table='Table 2', source_row=1, record_kind='baseline_volume',
            structure='Hippocampus', hemisphere='lh', group='PD', mean=4.0, sd=0.5, unit='ml'),
            dict(evidence_id='L', source_table='Table 2', source_row=1, record_kind='longitudinal_change', mean=-0.1),
            dict(evidence_id='V', source_table='Table 3', source_row=1, record_kind='log_volume', mean=3.2),
            dict(evidence_id='C', source_table='Table 2', source_row=1, record_kind='vertex_cluster', mean=2.0),
            dict(evidence_id='A', source_table='Table 3', source_row=1, record_kind='pial_surface_area', mean=1875)]
        (store / 'reviewed_pd_quantitative_tables.json').write_text(json.dumps(dict(sources=[dict(
            paper='Test paper', doi='test', processing_version='5.3.0', source_url='test', records=records)])))

    def test_only_absolute_native_volume_is_compared(self):
        rows = compare(self.result, 'TEST')
        self.assertAlmostEqual(rows[0]['measured'], 4.2)
        self.assertAlmostEqual(rows[0]['difference_from_group_mean'], 0.2)
        self.assertEqual([r['comparison_status'] for r in rows], ['descriptive_difference',
            'requires_followup', 'transformation_not_defined', 'context_only', 'surface_definition_mismatch'])
        self.assertTrue(all(r['difference_from_group_mean'] is None for r in rows[1:]))
        self.assertEqual(int(coverage(self.result, 'TEST').reference_records.sum()), 5)

    def test_version_or_atlas_mismatch_does_not_make_a_difference(self):
        self.result['features']['processing_software_version'] = '8.2.0'
        self.assertIsNone(compare(self.result, 'TEST')[0]['difference_from_group_mean'])
        self.result['features']['processing_software_version'] = '5.3.0'
        self.result['features']['atlas_name'] = 'Different atlas'
        self.assertEqual(compare(self.result, 'TEST')[0]['comparison_status'], 'not_comparable')

    def test_duplicate_features_are_not_arbitrarily_selected(self):
        self.result['features'] = pd.concat([self.result['features']] * 2)
        self.assertEqual(compare(self.result, 'TEST')[0]['comparison_status'], 'not_comparable')

    def test_source_approval_is_not_inferred(self):
        path = self.result['project_dir'] / 'workflow_sources/paper_reading_reviews/pd_paper_review_approvals.json'
        path.unlink()
        self.assertTrue(all(r['comparison_status'] == 'not_approved' for r in compare(self.result, 'TEST')))

    def test_triangle_plane_intersection(self):
        import numpy as np
        vertices = np.array([[0, 0, 0], [2, 2, 0], [2, 0, 2]], dtype=float)
        segments = surface_slice_segments(vertices, np.array([[0, 1, 2]]), 0, 1)
        self.assertEqual(segments.shape, (1, 2, 2))
        np.testing.assert_allclose(segments[0], [[1, 0], [0, 1]])
        self.assertEqual(len(surface_slice_segments(vertices, np.array([[0, 1, 2]]), 0, 3)), 0)

    def test_assistant_observation_is_not_human_approval(self):
        from assistant_visual_review import preview_html
        root = self.result['project_dir']
        image = root / 'sample.png'
        image.write_bytes(b'viewed-image')
        folder = root / 'outputs/assistant_visual_review_20261003'
        folder.mkdir(parents=True)
        record = dict(subject_id='TEST', status='requires_human_review', scope='Sampled only',
            observations=['Boundary <uncertain>'], images=[dict(relative_path='sample.png',
            sha256=hashlib.sha256(image.read_bytes()).hexdigest())])
        (folder / 'observations.json').write_text(json.dumps(dict(subjects=[record])))
        rendered = preview_html(self.result, 'TEST')
        self.assertIn('not human sign-off', rendered)
        self.assertIn('&lt;uncertain&gt;', rendered)
        image.write_bytes(b'changed-image')
        self.assertIn('stale', preview_html(self.result, 'TEST'))
        self.assertNotIn('Boundary', preview_html(self.result, 'TEST'))


if __name__ == '__main__':
    unittest.main()
