from workflow_paths import project_root
import json
import unittest
from pathlib import Path

from literature_audit import build_literature_audit, qualitative_candidates
from source_catalog_visibility import other_numeric_sources, patient_numeric_sources

ROOT = project_root()


class ADSignatureIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = build_literature_audit(ROOT)
        cls.rows = json.loads((ROOT/'workflow_sources/paper_reading_reviews/ad_signature_reported_statistics.json').read_text())

    def test_counts_and_catalog_visibility(self):
        papers = self.audit['papers']
        selected = papers[papers.legacy_codes.str.contains('AD-SIG|AD-WESTMAN')]
        self.assertEqual(dict(zip(selected.legacy_codes, selected.quantitative_records)),
                         {'AD-SIG-2009':70,'AD-SIG-2011':51,'AD-WESTMAN-2011':36})
        self.assertEqual(len(other_numeric_sources(selected)),3)
        self.assertTrue(patient_numeric_sources(selected).empty)
        self.assertTrue(selected.doi.ne('').all())

    def test_library_intake_does_not_enable_unvalidated_patient_comparisons(self):
        self.assertTrue(all(r['comparison_compatible'] is False for r in self.rows))
        self.assertTrue(all(r['source_location'] and r['source_url'] for r in self.rows))
        self.assertFalse(any(r.get('paper_code') in {'AD-SIG-2009','AD-SIG-2011','AD-WESTMAN-2011'}
                             for r in qualitative_candidates(self.audit)))

    def test_table_values_and_followup_labels(self):
        values = [r for r in self.rows if r.get('paper_code')=='AD-SIG-2011'
                  and r.get('roi_name')=='AD-signature summary measure' and r.get('cohort')=='MGH']
        self.assertEqual([r['reported_value'] for r in values],[2.49,2.35])
        self.assertTrue(all(r['diagnosis']=='Cognitively normal at baseline' for r in values))
        t4 = [r for r in self.rows if r.get('roi_name')=='Primary visual' and r.get('diagnosis')=='Incipient AD']
        self.assertEqual(t4[0]['percent_thinning'],-.39)
        for r in self.rows:
            if 'ad_like_count' in r:
                self.assertEqual(r['ad_like_count']+r['control_like_count'],r['cohort_sample_size'])


if __name__ == '__main__':
    unittest.main()
