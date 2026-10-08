import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from source_value_verification import ENIGMA_ID, HANGANU_ID, MANIFEST, render, verify


class SourceValueVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = json.loads((Path(__file__).parent / MANIFEST).read_text())
        for row in self.data['records']:
            for item in [dict(path=row['source_pdf']), *row['screenshots']]:
                path = self.root / 'workflow_sources' / item['path']
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'verified fixture bytes')
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if item['path'] == row['source_pdf']:
                    row['source_pdf_sha256'] = digest
                else:
                    item['sha256'] = digest
        self.stage = dict(records=[dict(evidence_id=ENIGMA_ID, effect_size=.357,
            regression_coefficient=2761.46, percent_difference=18.43, direction_eligible=False)])
        self.tables = dict(sources=[dict(doi='10.1093/brain/awu036', records=[dict(
            evidence_id=HANGANU_ID, structure='Pallidum', group='PD-MCI',
            record_kind='longitudinal_change', mean=-43.67, percent_change=1.4)])])
        self.save()

    def save(self):
        for name, data in [(MANIFEST, self.data),
            ('workflow_sources/Disease/PD/enigma_pd_stage_statistics.json', self.stage),
            ('workflow_sources/Disease/PD/reviewed_pd_quantitative_tables.json', self.tables)]:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))

    def test_completed_check_does_not_grant_direction_or_qc(self):
        before = copy.deepcopy((self.stage, self.tables))
        rows = verify(self.root)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['verification_status'] == 'completed' for r in rows))
        self.assertTrue(all(not r['direction_authorized'] and not r['patient_qc_changed'] for r in rows))
        self.assertEqual(before, (self.stage, self.tables))

    def test_render_reports_values_and_restrictions_not_pending_review(self):
        from research_report_release import assert_final_text
        content = render(self.root)
        assert_final_text(content)
        for value in ('Completed', '-0.357', '+0.357', '-43.67', '+1.40%',
                      'excluded from directional interpretation', 'not applicable to current single-scan'):
            self.assertIn(value, content)

    def test_source_or_screenshot_change_fails_closed(self):
        shot = self.root / 'workflow_sources' / self.data['records'][1]['screenshots'][0]['path']
        shot.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_direction_guard_cannot_be_lifted(self):
        self.stage['records'][0]['direction_eligible'] = True
        self.save()
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_sign_cannot_be_silently_corrected(self):
        self.tables['sources'][0]['records'][0]['percent_change'] = -1.4
        self.save()
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_missing_manifest_does_not_invent_verification(self):
        (self.root / MANIFEST).unlink()
        self.assertEqual(verify(self.root), [])
        self.assertEqual(render(self.root), '')


if __name__ == '__main__':
    unittest.main()
