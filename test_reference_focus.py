"""Reference routing tests with fabricated measurements, no network calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import ai_evidence_assistant as ai
from reference_focus import focus, filter_audit, PD_DOI, POTVIN_DOI
from test_ai_evidence_assistant import synthetic_answer


class ReferenceFocusTests(unittest.TestCase):
    def test_saved_focus_survives_reload_preserves_paths_and_keeps_backup(self):
        from user_pipeline import read_config
        from reference_focus import save_focus
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'config.json'
            original = dict(subjects_dir='subjects', metadata_csv='metadata.csv', output_dir='outputs')
            path.write_text(json.dumps(original))
            before = path.read_bytes()
            save_focus(read_config(path), 'PD')
            self.assertEqual(read_config(path)['reference_focus'], 'PD')
            self.assertEqual(json.loads(path.read_text())['subjects_dir'], 'subjects')
            backups = list(path.parent.glob('config.json.before_reference_*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), before)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            save_focus(read_config(path), 'PD')
            self.assertEqual(len(list(path.parent.glob('config.json.before_reference_*'))), 1)

    def result(self, root):
        return dict(reference_focus='PD', project_dir=root,
            features=pd.DataFrame([dict(subject_id='SYNTH', roi_name='synthetic',
                                       hemisphere='lh', imaging_metric='cortical_thickness',
                                       value_numeric=2.5, sex='Female', age=50)]),
            normative=pd.DataFrame([dict(subject_id='SYNTH', roi_name='synthetic',
                hemisphere='lh', imaging_metric='cortical_thickness', unit='mm',
                observed_value=2.5, calculation_status='calculated',
                range_status='within_95pi', lower_95pi=2, upper_95pi=3,
                expected_value=2.5)]))

    def test_focus_is_explicit_not_inferred_from_labels_or_ids(self):
        self.assertEqual(focus({'diagnosis': 'PD', 'subject_id': 'PPMI_123'}), 'all')
        self.assertEqual(focus({'reference_focus': 'PD'}), 'PD')
        with self.assertRaises(ValueError):
            focus({'reference_focus': 'typo'})

    def test_audit_filters_records_before_comparison_without_mutating_catalog(self):
        frame = pd.DataFrame({'doi': [PD_DOI, POTVIN_DOI, '10.1371/journal.pone.0279574']})
        audit = dict(papers=frame, evidence=frame)
        selected = filter_audit(audit, 'PD')
        self.assertEqual(len(audit['evidence']), 3)
        self.assertEqual(selected['evidence'].doi.tolist(), [PD_DOI, POTVIN_DOI])
        self.assertIs(filter_audit(audit, 'all'), audit)

    def test_pd_payload_does_not_run_zheng_even_when_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root/'workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json'
            file.parent.mkdir(parents=True)
            file.write_text('[]')
            result = self.result(root)
            pd_row = dict(evidence_id='synthetic_pd', measured=2.5,
                match_status='matched_for_context', normative_status='within_95pi',
                pd_minus_control_cohen_d=-0.1)
            with patch('comparison_atlas.comparison_features', return_value=result['features']), \
                    patch('pd_evidence.compare_result', return_value=[pd_row]) as pd_compare, \
                    patch('zheng_exploratory.compare', side_effect=AssertionError('AD must not run')):
                payload = ai.build_payload(result, 'SYNTH')
            pd_compare.assert_called_once_with(result, 'SYNTH')
            self.assertEqual(payload['allowed_conditions'], ['PD'])
            self.assertEqual(set(payload['sources']), {'Potvin', 'ENIGMA_PD'})
            self.assertEqual(len(payload['evidence']), 2)
            self.assertEqual(set(ai.outbound_payload(payload)['candidate_context_eligibility']), {'PD'})
            self.assertNotIn('Zheng_AD_Control', ai.serialise(payload))
            self.assertNotIn('SYNTH', ai.serialise(payload))
            answer = synthetic_answer()
            ai.validate_answer(answer, payload)
            answer['candidate_discussion'][0]['condition'] = 'AD'
            with self.assertRaises(ai.AIError):
                ai.validate_answer(answer, payload)
            general = dict(payload, reference_focus='all', allowed_conditions=['PD', 'AD', 'Control'])
            self.assertNotEqual(ai.payload_hash(payload), ai.payload_hash(general))

    def test_pd_report_and_export_never_call_ad(self):
        from concise_case_report import build_concise_report, export_concise_report
        with tempfile.TemporaryDirectory() as directory:
            result = self.result(Path(directory))
            result.update(links=pd.DataFrame(), fs_root=Path(directory), output_dir=Path(directory))
            pd_row = dict(source_structure='synthetic', metric='cortical_thickness',
                measured=2.5, unit='mm', normative_status='within_95pi',
                pd_minus_control_cohen_d=-0.1, p_as_reported='0.5',
                context='Within normative PI; neither confirms nor excludes PD',
                match_status='matched_for_context')
            with patch('pd_evidence.compare_result', return_value=[pd_row]), \
                    patch('zheng_exploratory.compare', side_effect=AssertionError('AD must not run')), \
                    patch('patient_evidence_ledger.compare', side_effect=AssertionError('AD ledger must not run')), \
                    patch('evidence_readiness.compare', side_effect=AssertionError('AD differential must not run')), \
                    patch('workflow_audit.method_compatibility', return_value=pd.DataFrame()), \
                    patch('workflow_audit.source_coverage', return_value=pd.DataFrame(columns=[
                        'source_title', 'doi', 'unique_evidence_rows', 'quantitative_records',
                        'reported_statistic_records', 'connected_group_effect_records',
                        'matched_group_effect_features', 'stage_reference_records', 'matched_stage_features',
                        'used_for_subject_qualitative', 'paired_features_exploratory', 'zero_evidence_reason',
                        'zero_match_reason'])), \
                    patch('workflow_audit.export_subject_audits'), \
                    patch('mri_viewer.skull_stripped_report_html', return_value='<p>Synthetic MRI</p>'):
                html = build_concise_report(result, 'SYNTH')
                self.assertIn('Reference focus: PD + Potvin', html)
                self.assertIn('Laansma', html)
                self.assertNotIn('Zheng', html)
                path = export_concise_report(result, 'SYNTH', directory)
                self.assertIn('Reference focus: PD + Potvin', path.read_text())
                from evidence_readiness import differential, reference_checks
                self.assertEqual(len(differential(result, 'SYNTH')), 1)
                self.assertEqual(len(reference_checks(result, 'SYNTH')), 1)
                from patient_evidence_ledger import ledger
                self.assertEqual(ledger(result, 'SYNTH').iloc[0].measured, 2.5)


if __name__ == '__main__':
    unittest.main()
