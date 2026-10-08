import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import ipywidgets as w
import nibabel as nib
import numpy as np
import pandas as pd

from segmentation_viewer import overlay_data, prepare_overlays, prepare_surface_overlays


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mri = self.root / 'subjects/SYNTH/mri'
        self.mri.mkdir(parents=True)
        self.shape = (8, 9, 10)
        self.affine = np.diag([1.0, 1.0, 1.0, 1.0])
        self.original = np.arange(np.prod(self.shape), dtype=np.float32).reshape(self.shape)
        self.mask = np.zeros(self.shape, dtype=np.float32)
        self.mask[2:6, 2:7, 2:8] = 100
        self.labels = np.zeros(self.shape, dtype=np.float32)
        self.labels[3:5, 3:6, 3:7] = 17
        for name, data in (('orig.mgz', self.original), ('brainmask.mgz', self.mask), ('aseg.mgz', self.labels)):
            nib.save(nib.MGHImage(data, self.affine), self.mri / name)

    def test_original_voxels_and_actual_brainmask_are_preserved(self):
        paths, manifest = prepare_overlays(self.root / 'subjects', 'SYNTH', self.root / 'cache')
        self.assertTrue(np.array_equal(nib.load(paths[0]).get_fdata(), self.original))
        self.assertTrue(np.array_equal(nib.load(paths[1]).get_fdata(), self.mask > 0))
        self.assertEqual(manifest['overlay_opacity'], 0.6)
        self.assertEqual(manifest['mask_definition'], 'brainmask.mgz > 0')

    def test_shifted_segmentation_cannot_be_overlaid(self):
        affine = self.affine.copy()
        affine[0, 3] = 2
        nib.save(nib.MGHImage(self.mask, affine), self.mri / 'brainmask.mgz')
        with self.assertRaisesRegex(ValueError, 'geometry mismatch'):
            overlay_data(self.root / 'subjects', 'SYNTH')

    def test_surface_tkregister_coordinates_are_converted_to_scanner_ras(self):
        surface_dir = self.mri.parent / 'surf'
        surface_dir.mkdir()
        original = nib.load(self.mri / 'orig.mgz')
        voxels = np.array([[2, 3, 4], [3, 3, 4], [2, 4, 4]], dtype=float)
        tk_ras = nib.affines.apply_affine(original.header.get_vox2ras_tkr(), voxels)
        for name in ('lh.white', 'rh.white', 'lh.pial', 'rh.pial'):
            nib.freesurfer.write_geometry(surface_dir / name, tk_ras, np.array([[0, 1, 2]]))
        paths = prepare_surface_overlays(self.root / 'subjects', 'SYNTH', self.root)
        points = nib.load(paths[0]).darrays[0].data
        np.testing.assert_allclose(points, nib.affines.apply_affine(original.affine, voxels), atol=1e-5)


class WorkflowTests(unittest.TestCase):
    def test_workflow_does_not_repeat_notebook_report_entry_or_change_status(self):
        from user_pipeline import workflow_summary_html
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'outputs/patient_audit_test'
            folder.mkdir(parents=True)
            (folder / 'PATIENT_OUTPUT_CHECKS.html').write_text('audit')
            (folder / 'patient_output_checks.json').write_text(json.dumps([
                dict(output_status='passed'), dict(output_status='processing_incomplete')]))
            approved = root / 'workflow_sources/paper_reading_reviews/pd_paper_review_approvals.json'
            approved.parent.mkdir(parents=True)
            approved.write_text(json.dumps(dict(papers=[dict(human_review_status='accepted',
                data_use_status='user_approved_research_use')])))
            final = root / 'outputs/final_reports_20261004/FINAL_REPORTS.html'
            final.parent.mkdir(parents=True)
            final.write_text('Final patient reports')
            repair = root / 'maintenance/topology_retry_0031_20261003/repair_status.json'
            repair.parent.mkdir(parents=True)
            repair.write_text(json.dumps(dict(promoted_to_workflow=False)))
            text = workflow_summary_html(root)
            self.assertEqual(text, '')
            self.assertEqual(final.read_text(), 'Final patient reports')
            self.assertEqual(json.loads(repair.read_text()), dict(promoted_to_workflow=False))

    def test_processing_failure_remains_visible_without_a_fabricated_report(self):
        from audit_all_patients import processing_failure_detail, write_audit
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subject = root / 'subjects/FAILED'
            (subject / 'scripts').mkdir(parents=True)
            (subject / 'scripts/recon-all.log').write_text('mris_fix_topology\nvertex 95608 has 0 face\nexited with ERRORS\n')
            detail = processing_failure_detail(subject)
            self.assertIn('has 0 face', detail)
            rows = [dict(subject_id='FAILED', output_status='processing_incomplete', processing_failure_detail=detail)]
            write_audit(rows, root, root / 'outputs/audit')
            text = (root / 'outputs/audit/PATIENT_OUTPUT_CHECKS.html').read_text()
            self.assertIn('0/1 passed', text)
            self.assertIn('vertex 95608', text)
            self.assertNotIn('FAILED report</a>', text)

    def test_user_approval_is_independent_of_computed_agreement(self):
        from literature_extraction_agreement import export_comparison
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'comparison.json'
            source.write_text(json.dumps(dict(papers=[dict(paper='Approved paper', doi='approved')],
                comparisons=[dict(doi='approved', record_key='ROI', field='effect', human_value=None,
                    automated_value=1, independent_pair=True)], limitations=[])))
            approval = dict(basis='Explicit user confirmation', papers=[dict(doi='approved',
                human_review_status='accepted', data_use_status='user_approved_research_use')])
            (root / 'pd_paper_review_approvals.json').write_text(json.dumps(approval))
            summary = export_comparison(source, root / 'out')[0]
            self.assertEqual(summary['human_review_status'], 'accepted')
            self.assertEqual(summary['data_use_status'], 'user_approved_research_use')
            self.assertIsNone(summary['agreement_percent'])
            self.assertEqual(summary['agreement_status'], 'paired_field_values_not_available')

    def test_extraction_agreement_excludes_unpaired_and_retains_disagreements(self):
        from literature_extraction_agreement import compare_fields
        rows = [dict(doi='test', record_key='ROI', field='effect', human_value=-0.17,
                     automated_value=-0.173, absolute_tolerance=0.005),
                dict(doi='test', record_key='ROI', field='sign', human_value='lower', automated_value='higher'),
                dict(doi='test', record_key='ROI', field='missing', human_value=None, automated_value=5)]
        self.assertEqual(compare_fields(rows).agreement.tolist(), ['agree', 'disagree', 'unpaired'])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            compare_fields(rows + rows[:1])

    def test_review_precedes_report_and_pending_review_does_not_approve(self):
        from report_quality import PreReportQC
        callback = Mock()
        viewer = Mock(box=w.VBox())
        qc = Mock(box=w.Accordion(children=[w.VBox()]))
        with patch('user_pipeline.participants', return_value=pd.DataFrame([dict(subject_id='SYNTH')])), \
             patch('segmentation_viewer.SegmentationViewer', return_value=viewer), \
             patch('report_quality.QCPanel', return_value=qc), \
             patch('report_quality.read_qc', return_value={'status': 'pending_visual_review'}) as review:
            panel = PreReportQC({'subjects_dir': Path('.')}, Path('.'), callback)
            self.assertTrue(panel.reviewed.disabled)
            panel.generate_reviewed()
            callback.assert_not_called()
            panel.generate_draft()
            callback.assert_called_once_with(False)
            review.return_value = {'status': 'accepted'}
            panel.generate_reviewed()
            self.assertEqual(callback.call_args.args, (True,))
            review.return_value = {'status': 'rejected'}
            panel.refresh()
            self.assertTrue(panel.draft.disabled)
            panel.close()

    def test_report_panel_has_no_ai_and_qc_is_before_numeric_report(self):
        from compact_report_panel import ReportPanel
        result = dict(run_manifest={'subject_ids': ['SYNTH']}, papers=pd.DataFrame(
            columns=['source_title', 'paper_id']), fs_root=Path('.'), output_dir=Path('.'))
        mri = Mock(box=w.VBox(), status=w.HTML(), viewer=None)
        qc = Mock(box=w.VBox())
        with patch('compact_report_panel.SubjectMRIViewer', return_value=mri), \
             patch('report_quality.QCPanel', return_value=qc), patch.object(ReportPanel, 'refresh'), \
             patch('compact_report_panel.display'):
            panel = ReportPanel(result)
            self.assertFalse(hasattr(panel, 'ai'))
            self.assertLess(panel.box.children.index(qc.box), panel.box.children.index(panel.report))
            panel.show()
            panel.close()

    def test_reviewed_analysis_checks_qc_before_creating_numeric_outputs(self):
        from user_pipeline import analyze
        with tempfile.TemporaryDirectory() as directory, \
             patch('user_pipeline.status', return_value=[dict(subject_id='SYNTH', complete=True)]), \
             patch('report_quality.read_qc', return_value={'status': 'pending_visual_review'}):
            config = dict(subjects_dir=Path(directory), output_dir=Path(directory) / 'outputs')
            with self.assertRaisesRegex(ValueError, 'requires accepted segmentation QC'):
                analyze(config, Path(__file__).parent, require_reviewed_qc=True)
            self.assertFalse(config['output_dir'].exists())

    def test_pd_processing_version_is_checked_against_reference(self):
        from pd_evidence import compare_records
        patient = dict(subject_id='SYNTH', roi_name='fusiform', hemisphere='lh',
                       imaging_metric='cortical_thickness', atlas_name='Desikan-Killiany',
                       unit='mm', value_numeric=2.5, processing_software_version='8.2')
        reference = dict(patient, effect_size=-0.2, source_structure='L_fusiform',
            processing_software_version='5.3.0', n_patients=2357, n_controls=1182,
            human_review_status='pending_human_review', evidence_id='SYNTH-REF',
            doi='10.1002/mds.28706', source_data_url='https://example.org')
        rows = compare_records([patient], [], [reference], 'SYNTH')
        self.assertEqual(rows[0]['match_status'], 'unavailable')
        self.assertIn('processing versions differ', rows[0]['context'])

    def test_full_measurement_table_preserves_normal_and_missing_rows(self):
        from concise_case_report import measurement_table
        rows = pd.DataFrame([dict(roi_name='B', hemisphere='rh', imaging_metric='roi_volume',
            calculation_status='not_calculated', range_status='not_assessed', exclusion_reason='No model'),
            dict(roi_name='A', hemisphere='lh', imaging_metric='cortical_thickness',
            calculation_status='calculated', range_status='within_95pi')])
        table = measurement_table(rows)
        self.assertEqual(len(table), 2)
        self.assertEqual(table.roi_name.tolist(), ['A', 'B'])
        self.assertEqual(table.iloc[1].exclusion_reason, 'No model')


if __name__ == '__main__':
    unittest.main()
