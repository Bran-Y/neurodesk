"""Assistant inspection must stay source-bound and distinct from manual acceptance."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from assistant_visual_review import detailed_record, preview_html
from report_quality import QC_FILES, read_qc, source_fingerprint


class AssistantReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sid = 'PPMI_41282'
        self.result = dict(project_dir=str(self.root), fs_root=str(self.root / 'subjects'))
        for name in QC_FILES:
            path = self.root / 'subjects' / self.sid / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        self.folder = self.root / 'outputs/pd_qc_detailed_20261003'
        self.folder.mkdir(parents=True)
        self.picture = self.folder / 'test.png'
        self.picture.write_bytes(b'inspected image fixture')
        self.record = dict(subject_id=self.sid, source_fingerprint=source_fingerprint(self.result['fs_root'], self.sid)[0],
            reviewer_role='assistant', human_qc_accepted=False, status='targeted_review_needed',
            reviewed_at='2026-10-03', scope='Only inspected slices', summary='No human acceptance',
            checks=[dict(check='mask', assessment='review', observation='<not markup>', action='inspect')],
            images=[dict(relative_path=str(self.picture.relative_to(self.root)),
                         sha256=hashlib.sha256(self.picture.read_bytes()).hexdigest())])
        self.save()

    def save(self):
        (self.folder / 'review_observations.json').write_text(json.dumps(dict(subjects=[self.record])))

    def test_valid_detailed_record_does_not_accept_manual_qc(self):
        self.assertEqual(detailed_record(self.result, self.sid)['reviewer_role'], 'assistant')
        self.assertEqual(read_qc(self.result, self.sid)['status'], 'pending_visual_review')
        rendered = preview_html(self.result, self.sid)
        self.assertIn('&lt;not markup&gt;', rendered)
        self.assertNotIn('<not markup>', rendered)
        self.assertIn('not human sign-off', rendered)

    def test_source_change_invalidates_observations(self):
        (self.root / 'subjects' / self.sid / 'mri/orig.mgz').write_bytes(b'new acquisition')
        self.assertEqual(detailed_record(self.result, self.sid)['status'], 'stale_assistant_review')
        self.assertNotIn('data:image', preview_html(self.result, self.sid))

    def test_missing_source_invalidates_observations(self):
        (self.root / 'subjects' / self.sid / 'surf/rh.pial').unlink()
        self.assertEqual(detailed_record(self.result, self.sid)['status'], 'stale_assistant_review')

    def test_image_change_invalidates_observations(self):
        self.picture.write_bytes(b'not the image viewed')
        self.assertEqual(detailed_record(self.result, self.sid)['status'], 'stale_assistant_review')

    def test_cannot_claim_human_acceptance(self):
        self.record['human_qc_accepted'] = True
        self.save()
        with self.assertRaises(ValueError):
            detailed_record(self.result, self.sid)

    def test_rejects_path_traversal(self):
        self.record['images'][0]['relative_path'] = '../outside.png'
        self.save()
        with self.assertRaises(ValueError):
            detailed_record(self.result, self.sid)

    def test_other_patient_not_reused(self):
        self.assertIsNone(detailed_record(self.result, 'PPMI_41289'))


if __name__ == '__main__':
    unittest.main()
