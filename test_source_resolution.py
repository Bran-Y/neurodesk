import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

from resolve_enigma_sources import apply_resolutions, CORRECTIONS, PDF_SHA, CONFLICT_NOTE
from source_resolution_exports import compare_source_refresh

ROOT = Path(__file__).parent
DATA = ROOT / 'workflow_sources/Disease/PD'


class SourceResolutionTests(unittest.TestCase):
    def test_idempotent_and_human_history_unchanged(self):
        whole = json.loads((DATA / 'enigma_pd_group_statistics.json').read_text())
        stage = json.loads((DATA / 'enigma_pd_stage_statistics.json').read_text())
        before = copy.deepcopy((whole, stage))
        apply_resolutions(whole, stage, PDF_SHA)
        self.assertEqual(before, (whole, stage))
        with self.assertRaises(ValueError):
            apply_resolutions(whole, stage, 'changed PDF')
        whole['records'][next(i for i, r in enumerate(whole['records'])
                             if r['evidence_id'] in CORRECTIONS)]['source_page'] = 0
        with self.assertRaises(ValueError):
            apply_resolutions(whole, stage, PDF_SHA)

    def test_export_guard_rejects_patient_value_change(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / 'a', Path(folder) / 'b'
            a.mkdir()
            b.mkdir()
            pd.DataFrame([dict(measured=123)]).to_csv(a / 'measurements.csv', index=False)
            pd.DataFrame([dict(measured=123)]).to_csv(b / 'measurements.csv', index=False)
            checked, changes = compare_source_refresh(a / 'report.html', b / 'report.html')
            self.assertEqual(checked, ['measurements.csv'])
            self.assertFalse(changes)
            pd.DataFrame([dict(measured=124)]).to_csv(b / 'measurements.csv', index=False)
            with self.assertRaises(AssertionError):
                compare_source_refresh(a / 'report.html', b / 'report.html')

    def test_compact_qc_has_outcome_without_human_acceptance(self):
        from report_quality import qc_html
        with patch('report_quality.read_qc', return_value={'status': 'pending_visual_review'}), \
             patch('assistant_visual_review.detailed_record',
                   return_value=dict(status='sampled_review_complete_human_qc_pending',
                                     final_outcome='Selected boundaries broadly aligned.')):
            content = qc_html({}, 'test', compact=True)
        self.assertIn('Selected boundaries broadly aligned.', content)
        self.assertIn('pending_visual_review', content)
        self.assertIn('Full-volume manual confirmation remains incomplete.', content)
        self.assertNotIn('reviewed_at', content)

    def test_derived_atlas_context_follows_only_six_reference_corrections(self):
        from pd_evidence import compare_records
        whole = json.loads((DATA / 'enigma_pd_group_statistics.json').read_text())['records']
        refs = [r for r in whole if r['evidence_id'] in CORRECTIONS]
        patient = [dict(r, subject_id='SYNTH', value_numeric=100) for r in refs]
        norm = [dict(r, calculation_status='calculated', range_status='within_95pi') for r in patient]
        old = pd.DataFrame(compare_records(patient, norm,
            [dict(r, direction_eligible=False) for r in refs], 'SYNTH'))
        new = pd.DataFrame(compare_records(patient, norm, refs, 'SYNTH'))
        # Preserve mixed numeric/censored source columns exactly as CSV readers do.
        for frame in (old, new):
            frame['regression_ci_upper'] = frame.regression_ci_upper.astype(object)
            frame.at[0, 'regression_ci_upper'] = '<0.001'
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / 'a', Path(folder) / 'b'
            a.mkdir()
            b.mkdir()
            for directory, frame in ((a, old), (b, new)):
                frame.to_csv(directory / 'SYNTH_pd_source_comparisons.csv', index=False)
                frame[['subject_id', 'evidence_id', 'match_status', 'context']].to_csv(
                    directory / 'SYNTH_atlas_comparisons.csv', index=False)
            checked, changes = compare_source_refresh(a / 'report.html', b / 'report.html')
            self.assertEqual(len(checked), 2)
            self.assertEqual(len(changes), 6)
            new.at[0, 'measured'] = 999
            new.to_csv(b / 'SYNTH_pd_source_comparisons.csv', index=False)
            with self.assertRaises(AssertionError):
                compare_source_refresh(a / 'report.html', b / 'report.html')


if __name__ == '__main__':
    unittest.main()
