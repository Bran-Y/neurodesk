"""Compact presentation must not manufacture review or lose available values."""
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
from concise_case_report import demographic_summary
from report_interpretation import status_html
from report_quality import qc_html
from review_pending_reports import presentation, compare_numeric


class PresentationTests(unittest.TestCase):
    def test_optional_missing_fields_hidden_zero_retained(self):
        self.assertEqual(demographic_summary(dict(age=50, sex='Male')), 'Age: 50 | Sex: Male')
        self.assertIn('CDR: 0', demographic_summary(dict(age=50, sex='Male', cdr=0)))

    def test_pending_qc_not_accepted_and_review_traces_hidden(self):
        with patch('report_quality.read_qc', return_value={'status': 'pending_visual_review'}), patch('assistant_visual_review.preview_html', return_value='<p>Evidence retained</p>'):
            text = qc_html({}, 'test', compact=True)
        self.assertIn('pending_visual_review', text)
        self.assertNotIn('Evidence retained', text)
        self.assertNotIn('<details>', text)
        self.assertNotIn('pending_visual_review:', text)
        self.assertFalse(presentation(text)['empty_pending_note'])

    def test_accepted_qc_hides_signature_and_process_note(self):
        with patch('report_quality.read_qc', return_value={'status': 'accepted',
                'reviewer': 'Reviewer name', 'reviewed_at': '2026-10-04', 'note': 'Review trace'}):
            text = qc_html({}, 'test', compact=True)
        self.assertIn('accepted', text)
        for process_text in ('Reviewer name', '2026-10-04', 'Review trace'):
            self.assertNotIn(process_text, text)

    def test_review_note_retained(self):
        with patch('report_quality.read_qc', return_value={'status': 'rejected', 'note': 'wrong segmentation'}), patch('assistant_visual_review.preview_html', return_value=''):
            self.assertIn('wrong segmentation', qc_html({}, 'test', compact=True))

    def test_classification_still_unassigned(self):
        self.assertIn('data-assigned-diagnosis="none"', status_html(compact=True))
        self.assertIn('Not estimated.', status_html(compact=True))

    def test_nested_closed_details_not_counted_as_visible(self):
        report = presentation('<p>Visible</p><details><summary>more</summary><p>Hidden</p><details open><p>Also hidden</p></details></details><details open><p>Shown</p></details>')
        self.assertEqual(report['visible_paragraphs'], 2)
        self.assertEqual(report['total_paragraphs'], 4)

    def test_duplicate_detection(self):
        self.assertEqual(presentation('<p>Same</p><p>Same</p>')['duplicate_visible_paragraphs'], ['Same'])

    def test_broken_details_rejected(self):
        with self.assertRaises(ValueError):
            presentation('<details><p>oops</p>')

    def test_only_prose_and_named_metadata_can_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old, new = root / 'old', root / 'new'
            old.mkdir(); new.mkdir()
            (old / 'values.csv').write_text('value,context\n2,old text\n')
            (new / 'values.csv').write_text('value,context,nominal_p_below_0_05\n2,new text,True\n')
            verified, updates = compare_numeric(old / 'report.html', new / 'report.html')
            self.assertEqual(verified, ['values.csv'])
            self.assertEqual(len(updates), 2)
            (new / 'values.csv').write_text('value,context\n3,new text\n')
            with self.assertRaises(AssertionError):
                compare_numeric(old / 'report.html', new / 'report.html')

    def test_interpretation_cannot_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old, new = root / 'old', root / 'new'
            old.mkdir(); new.mkdir()
            (old / 'interpretation.json').write_text('{"assigned_diagnosis":null}')
            (new / 'interpretation.json').write_text('{"assigned_diagnosis":"PD"}')
            with self.assertRaises(ValueError):
                compare_numeric(old / 'report.html', new / 'report.html')


if __name__ == '__main__':
    unittest.main()
