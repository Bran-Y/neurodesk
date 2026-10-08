"""Synthetic regression checks; never approve real subjects or call external AI."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import ipywidgets as w
import pandas as pd
import report_quality as quality
import ai_evidence_assistant as ai
from test_ai_evidence_assistant import synthetic_payload, synthetic_answer, synthetic_pd_payload


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result = {'project_dir': self.root, 'fs_root': self.root / 'subjects'}
        for name in quality.QC_FILES:
            path = self.result['fs_root'] / 'SYNTH' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic fixture')
        self.fingerprint, _ = quality.source_fingerprint(self.result['fs_root'], 'SYNTH')
        self.checks = dict.fromkeys(quality.QC_CHECKS, True)

    def save(self, **overrides):
        args = dict(reviewer='Synthetic reviewer', note='Synthetic test only', checks=self.checks,
                    decision='accepted', expected_fingerprint=self.fingerprint)
        args.update(overrides)
        return quality.save_qc(self.result, 'SYNTH', **args)

    def test_pending_does_not_become_accepted_without_checks_and_reviewer(self):
        self.assertEqual(quality.read_qc(self.result, 'SYNTH')['status'], 'pending_visual_review')
        for overrides in ({'reviewer': ''}, {'note': ''}, {'checks': {}}, {'decision': None}):
            with self.assertRaises(ValueError):
                self.save(**overrides)
        self.assertFalse(quality.qc_directory(self.result, 'SYNTH').exists())

    def test_record_private_append_only_and_source_change_invalidates(self):
        self.save()
        self.assertEqual(quality.read_qc(self.result, 'SYNTH')['status'], 'accepted')
        self.save(decision='rejected', note='Synthetic second inspection')
        records = list(quality.qc_directory(self.result, 'SYNTH').glob('*.json'))
        self.assertEqual(len(records), 2)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in records))
        self.assertEqual(quality.read_qc(self.result, 'SYNTH')['status'], 'rejected')
        (self.result['fs_root'] / 'SYNTH' / 'stats/aseg.stats').write_text('changed')
        self.assertEqual(quality.read_qc(self.result, 'SYNTH')['status'], 'stale_review')
        with self.assertRaises(ValueError):
            self.save()

    def test_missing_files_cannot_be_accepted(self):
        (self.result['fs_root'] / 'SYNTH' / 'mri/aseg.mgz').unlink()
        self.fingerprint, _ = quality.source_fingerprint(self.result['fs_root'], 'SYNTH')
        with self.assertRaises(ValueError):
            self.save()
        self.save(decision='rejected', note='Synthetic missing segmentation', checks={})
        self.assertEqual(quality.read_qc(self.result, 'SYNTH')['status'], 'rejected')
        with self.assertRaises(ValueError):
            quality.source_fingerprint(self.result['fs_root'], '../escape')

    def test_selection_resets_review_fields_and_close_detaches(self):
        subject = w.Dropdown(options=['SYNTH', 'OTHER'])
        callback = Mock()
        panel = quality.QCPanel(self.result, subject, callback)
        panel.reviewer.value = 'Not a real reviewer'
        panel.note.value = 'Not a real review'
        panel.checks['motion_artifacts'].value = True
        subject.value = 'OTHER'
        self.assertEqual(panel.reviewer.value, '')
        self.assertFalse(panel.checks['motion_artifacts'].value)
        panel.close()
        subject.value = 'SYNTH'
        self.assertEqual(panel.sid, 'OTHER')
        panel.record()
        callback.assert_not_called()

    def test_coverage_accounts_for_missing_and_unmatched_separately(self):
        self.result['normative'] = pd.DataFrame([
            dict(subject_id='SYNTH', calculation_status='calculated', range_status='within_95pi'),
            dict(subject_id='SYNTH', calculation_status='calculated', range_status='above_95pi'),
            dict(subject_id='SYNTH', calculation_status='not_calculated', range_status='not_assessed', exclusion_reason='No compatible model')])
        refs = [dict(match_status='unavailable', source_structure='thalamus', context='Boundary unresolved')]
        with patch('pd_evidence.compare_result', return_value=refs):
            rendered = quality.coverage_html(self.result, 'SYNTH')
        self.assertIn('3 measurements = 1 within + 1 outside + 1 not calculated', rendered)
        self.assertIn('No compatible model', rendered)
        self.assertIn('Boundary unresolved', rendered)

    def test_saved_report_link_has_no_kernel_dependency(self):
        with patch.dict(os.environ, {'JUPYTERHUB_SERVICE_PREFIX': '/user/test/', 'JUPYTER_SERVER_ROOT': str(self.root)}):
            rendered = quality.saved_report_link(self.root/'report one.html', 'SYNTH')
        self.assertIn('/user/test/files/report%20one.html', rendered)
        self.assertIn('Saved snapshot, not live', rendered)

    def test_source_catalog_counts_connected_pd_rows_without_fabricating_registry_records(self):
        papers = pd.DataFrame([dict(doi='10.1002/mds.28706', unique_evidence_rows=0, zero_evidence_reason='No records'),
                               dict(doi='10.example/unrelated', unique_evidence_rows=0, zero_evidence_reason='No records')])
        comparisons = pd.DataFrame([dict(evidence_id='PD1', match_status='matched_for_context'),
                                    dict(evidence_id='PD1', match_status='matched_for_context'),
                                    dict(evidence_id='PD2', match_status='unavailable')])
        joined = quality.source_contributions(papers, comparisons)
        self.assertEqual(joined.connected_group_effect_records.tolist(), [2, 0])
        self.assertEqual(joined.matched_group_effect_features.tolist(), [1, 0])
        self.assertEqual(joined.unique_evidence_rows.tolist(), [0, 0])
        self.assertIn('separate PD', joined.iloc[0].zero_evidence_reason)
        self.assertEqual(papers.iloc[0].zero_evidence_reason, 'No records')


class LifecycleTests(unittest.TestCase):
    def test_config_and_reference_changes_clear_previous_panel_and_rerun_disables_old_actions(self):
        import user_pipeline
        panels = []
        def panel_factory(result):
            panel = Mock()
            panels.append(panel)
            return panel
        with patch('notebook_input.input_form', return_value=w.VBox()), \
             patch('IPython.display.display') as display, patch('user_pipeline.read_config', return_value={}), \
             patch('user_pipeline.analyze', return_value={}), \
             patch('compact_report_panel.ReportPanel', side_effect=panel_factory):
            user_pipeline.show()
            box = display.call_args.args[0]
            path, reference, controls = box.children[2], box.children[3], box.children[6]
            run = controls.children[2]
            run.click()
            path.value = 'different.json'
            panels[0].close.assert_called_once()
            run.click()
            reference.value = 'PD'
            panels[1].close.assert_called_once()
            replacement = user_pipeline.show()
            self.assertTrue(run.disabled)
            run.click()
            self.assertEqual(len(panels), 2)
            user_pipeline._close_active_ui()

    def test_report_panel_close_detaches_selection_and_mri_callbacks(self):
        from compact_report_panel import ReportPanel
        panel = ReportPanel.__new__(ReportPanel)
        panel.closed = False
        panel.ai = Mock()
        panel.qc = Mock()
        panel.subject = w.Dropdown(options=['SYNTH', 'OTHER'])
        panel.subject.observe(panel.refresh, names='value')
        for name in ('section', 'roi', 'paper'):
            widget = w.Text()
            setattr(panel, name, widget)
            widget.observe(panel.refresh_details, names='value')
        panel.mri_button = w.Button()
        panel.mri_button.on_click(panel.open_mri)
        panel.mri = Mock()
        panel.report, panel.detail, panel.status, panel.box = w.HTML(), w.HTML(), w.HTML(), w.VBox()
        panel.close()
        panel.close()
        panel.subject.value = 'OTHER'
        panel.mri_button.click()
        panel.ai.close.assert_called_once()
        panel.qc.close.assert_called_once()
        panel.mri.show.assert_not_called()


class CitationTests(unittest.TestCase):
    def test_standalone_ai_snapshot_is_private_and_identifies_subject_scope_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            payload, answer = synthetic_payload(), synthetic_answer()
            path = quality.export_ai_snapshot({'output_dir': directory}, 'SYNTH', payload, {'answer': answer})
            rendered = path.read_text()
            self.assertIn('<h2>SYNTH</h2>', rendered)
            self.assertIn(ai.payload_hash(payload), rendered)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_snapshot_values_are_visible_not_generated(self):
        payload, answer = synthetic_payload(), synthetic_answer()
        rendered = ai.render_explanation({'answer': answer}, payload)
        self.assertIn('Verified values behind AI citations', rendered)
        self.assertIn('Observed value: 2.5', rendered)
        self.assertIn('Upper 95pi: 3.2', rendered)
        self.assertNotIn('Evidence-based conclusion:', rendered)

    def test_pd_only_missing_norm_does_not_publish_normality_claim(self):
        payload, answer = synthetic_pd_payload(), synthetic_answer()
        pd_row = next(row for row in payload['evidence'] if row['source'] == 'ENIGMA_PD')
        pd_row['normative_status'] = 'not_calculated'
        answer['findings'][0]['evidence_ids'] = [pd_row['evidence_id']]
        answer['findings'][0]['interpretation'] = 'The supplied measurement is normal.'
        rendered = ai.render_explanation({'answer': answer}, payload)
        self.assertIn('AI interpretation withheld', rendered)
        self.assertNotIn('The supplied measurement is normal.', rendered)


if __name__ == '__main__':
    unittest.main()
