import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from research_report_release import final_frame, assert_final_text, verify_barnes
from report_quality import qc_html


class ReleaseTests(unittest.TestCase):
    def test_historical_pending_is_not_promoted_to_acceptance(self):
        source = pd.DataFrame([dict(doi='unknown', review_status='pending_human_review',
                                    effect=0.2, context='Not comparable')])
        before = source.copy(deep=True)
        shown = final_frame(source)
        pd.testing.assert_frame_equal(source, before)
        self.assertNotIn('review_status', shown)
        self.assertIn('Not used', shown.evidence_disposition.iloc[0])
        self.assertEqual(shown.effect.iloc[0], .2)
        assert_final_text(shown.to_html(index=False))

    def test_conflict_and_rejection_stay_excluded(self):
        for row in (dict(direction_eligible=False, review_status='accepted'),
                    dict(review_status='rejected', match_status='matched_for_context')):
            shown = final_frame(pd.DataFrame([row]))
            self.assertTrue(shown.evidence_disposition.iloc[0].startswith('Excluded'))

    def test_single_scan_does_not_become_longitudinal(self):
        shown = final_frame(pd.DataFrame([dict(comparison_status='requires_followup',
                                              human_review_status='accepted', measured=None)]))
        self.assertIn('single-scan', shown.evidence_disposition.iloc[0])
        self.assertIsNone(shown.measured.iloc[0])

    def test_qc_pending_allowed_non_qc_pending_and_draft_rejected(self):
        assert_final_text('<h4>Segmentation QC</h4><p>pending_visual_review</p>')
        for text in ('Research draft', 'pending_human_review', 'pending review',
                     'source_checked_pending_human_review'):
            with self.assertRaises(ValueError):
                assert_final_text(text)

    def test_accepted_qc_does_not_say_human_confirmation_incomplete(self):
        with patch('report_quality.read_qc', return_value={'status': 'accepted'}), \
             patch('assistant_visual_review.detailed_record', return_value={
                 'status': 'sampled', 'final_outcome': 'sampled observations'}):
            shown = qc_html({}, 'SYNTH', compact=True)
        self.assertNotIn('confirmation remains incomplete', shown)

    def test_barnes_exact_abstract_values_and_no_patient_interval(self):
        path = Path(__file__).parent / 'workflow_sources/paper_reading_reviews/barnes_2005_reported_statistics.json'
        records = json.loads(path.read_text())
        verify_barnes(records)
        records[0]['reported_value'] = 1.8
        with self.assertRaises(ValueError):
            verify_barnes(records)

    def test_all_current_non_qc_records_have_final_dispositions(self):
        from literature_audit import build_literature_audit
        audit = build_literature_audit(Path(__file__).parent)
        shown = final_frame(audit['evidence'])
        self.assertEqual(len(shown), len(audit['evidence']))
        self.assertFalse(shown.evidence_disposition.str.contains('pending|draft', case=False).any())
        self.assertEqual(sum(shown.doi.eq('10.1159/000084560')), 6)

    def test_final_generation_keeps_qc_gate_and_rejection_guard(self):
        import ipywidgets as w
        from report_quality import PreReportQC
        callback = Mock()
        with patch('user_pipeline.participants', return_value=pd.DataFrame([dict(subject_id='SYNTH')])), \
             patch('segmentation_viewer.SegmentationViewer', return_value=Mock(box=w.VBox())), \
             patch('report_quality.QCPanel', return_value=Mock(box=w.Accordion(children=[w.VBox()]))), \
             patch('report_quality.read_qc', return_value={'status':'pending_visual_review'}) as review:
            panel = PreReportQC({'subjects_dir': '.'}, '.', callback)
            self.assertNotIn('draft', panel.state.value.lower())
            self.assertIn('final research', panel.draft.description)
            panel.generate_reviewed()
            callback.assert_not_called()
            panel.generate_draft()
            callback.assert_called_once_with(False)
            review.return_value = {'status': 'rejected'}
            panel.refresh()
            self.assertTrue(panel.draft.disabled)
            panel.close()


if __name__ == '__main__':
    unittest.main()
