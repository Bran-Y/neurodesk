import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from hanganu_figure_review import MANIFEST, render, verify


class HanganuFigureReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = json.loads((Path(__file__).parent / MANIFEST).read_text())
        self.source = self.root / 'workflow_sources' / self.data['source_pdf']
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'primary PDF fixture')
        self.data['source_pdf_sha256'] = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.save()

    def save(self):
        path = self.root / MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.data))

    def test_six_textual_summaries_without_patient_use_or_qc(self):
        data = verify(self.root)
        self.assertEqual(len(data['records']), 6)
        self.assertFalse(data['patient_numeric_use'])
        self.assertFalse(data['patient_qc_changed'])
        self.assertTrue(all(r['corrected_significant_per_roi'] is None for r in data['records']))

    def test_source_change_fails_closed(self):
        self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_no_invented_p_or_r_or_roi_correction(self):
        for field, value in [('exact_p', .001), ('exact_r', .8), ('corrected_significant_per_roi', True)]:
            self.data['records'][0][field] = value
            self.save()
            with self.assertRaises(ValueError):
                verify(self.root)
            self.data['records'][0][field] = None

    def test_figure_two_cannot_be_promoted_to_corrected(self):
        self.data['figures'][1]['reported_statistical_status'] = 'FDR p<0.05'
        self.save()
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_visual_display_threshold_does_not_establish_significance(self):
        self.data['figures'][0]['display_threshold_is_corrected_status'] = True
        self.save()
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_render_final_findings_not_pending_review(self):
        from research_report_release import assert_final_text
        content = render(self.root)
        assert_final_text(content)
        self.assertIn('Not reported by the source', content)
        self.assertIn('uncorrected', content)
        self.assertIn('Left lateral occipital; left fusiform', content)
        self.assertIn('Not specified in the Results sentence', content)

    def test_missing_manifest_does_not_invent_review(self):
        (self.root / MANIFEST).unlink()
        self.assertIsNone(verify(self.root))
        self.assertEqual(render(self.root), '')


if __name__ == '__main__':
    unittest.main()
