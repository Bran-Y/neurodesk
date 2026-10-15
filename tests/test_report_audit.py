import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from audit_report_interpretation import audit
from report_interpretation import assessment, status_html


class ReportAuditTests(unittest.TestCase):
    def check(self, expected_sid='OAS1_0004_MR1', candidate=False, assigned=None, heading_sid=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / (expected_sid + '_concise_report.html')
            heading = heading_sid or expected_sid
            report.write_text('<h3>Subject: ' + heading + '</h3>' + status_html() +
                ('<p>AD remains a candidate for further evaluation.</p>' if candidate else ''))
            record = dict(subject_id=expected_sid, **assessment())
            record['exploratory_candidates'] = ['AD-like regional pattern'] if candidate else []
            record['assigned_diagnosis'] = assigned
            report.with_name(expected_sid + '_interpretation.json').write_text(json.dumps(record))
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps([dict(subject_id=expected_sid, report_path=str(report), processing_complete=True)]))
            with contextlib.redirect_stdout(io.StringIO()):
                audit(root, manifest, root / 'audit')
            return json.loads((root / 'audit/REPORT_INTERPRETATION_AUDIT.json').read_text())

    def test_control_candidate_is_flagged_not_rewritten(self):
        data = self.check(candidate=True)
        row = data['cases'][0]
        self.assertTrue(row['adlike_candidate'])
        self.assertTrue(row['label_conflict'])
        self.assertEqual(row['check_status'], 'needs_review')
        self.assertIsNone(data['summary']['accuracy'])

    def test_adlike_in_ad_case_is_not_a_conflict(self):
        self.assertFalse(self.check('OAS1_0003_MR1', candidate=True)['cases'][0]['label_conflict'])

    def test_known_pd_with_ad_candidate_requires_review(self):
        self.assertTrue(self.check('PPMI_41282', candidate=True)['cases'][0]['label_conflict'])

    def test_unknown_label_cannot_pass_label_verification(self):
        self.assertIsNone(self.check('OAS1_0022_MR1', candidate=True)['cases'][0]['label_conflict'])

    def test_additional_user_confirmed_ad_cases_align(self):
        for sid in ('OAS1_0015_MR1', 'OAS1_0028_MR1'):
            row = self.check(sid, candidate=True)['cases'][0]
            self.assertEqual(row['expected_group'], 'AD')
            self.assertFalse(row['label_conflict'])

    def test_wrong_subject_or_assigned_diagnosis_fails(self):
        for kwargs in (dict(heading_sid='OAS1_0003_MR1'), dict(assigned='AD')):
            row = self.check(**kwargs)['cases'][0]
            self.assertEqual(row['check_status'], 'needs_review')
            self.assertTrue(row['unsafe_classification_markers'])


if __name__ == '__main__':
    unittest.main()
