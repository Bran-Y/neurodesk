"""Portable entry tests; synthetic fixtures only, no participant files needed."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from user_pipeline import read_config, participants, completed, analyze


class UserPipelineTests(unittest.TestCase):
    def test_config_paths_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'metadata.csv').write_text('subject_id,age,sex,scanner_field_strength,scanner_manufacturer\nCASE_A,60,Female,3,Siemens\n')
            path = root/'config.json'
            path.write_text(json.dumps(dict(subjects_dir='subjects', metadata_csv='metadata.csv', output_dir='outputs')))
            config = read_config(path)
            self.assertEqual(config['subjects_dir'], (root/'subjects').resolve())
            self.assertEqual(participants(config).iloc[0].subject_id, 'CASE_A')
            (root/'metadata.csv').write_text('subject_id,age,sex,scanner_field_strength,scanner_manufacturer\nCASE_A,60,Female,,\n')
            with self.assertRaises(ValueError):
                participants(config)

    def test_version_completion_and_running_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(completed(root)[0])
            for name in ['scripts/recon-all.done','scripts/recon-all.log','scripts/build-stamp.txt',
                         'mri/brain.mgz','stats/aseg.stats','stats/lh.aparc.stats','stats/rh.aparc.stats']:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic test')
            (root/'scripts/recon-all.log').write_text('finished without error')
            (root/'scripts/build-stamp.txt').write_text('freesurfer-v8.2.0')
            self.assertFalse(completed(root)[0])
            (root/'scripts/build-stamp.txt').write_text('freesurfer-v5.3.0')
            self.assertTrue(completed(root)[0])
            (root/'scripts/IsRunning.lh+rh').touch()
            self.assertFalse(completed(root)[0])

    def test_incomplete_cohort_never_runs_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            meta = root/'metadata.csv'
            meta.write_text('subject_id,age,sex,scanner_field_strength,scanner_manufacturer\nNEW_CASE,60,Female,3,Siemens\n')
            config = dict(subjects_dir=root/'fs', metadata_csv=meta, output_dir=root/'outputs')
            with patch('finished_evidence_workflow.run_finished_workflow') as run:
                with self.assertRaises(ValueError):
                    analyze(config)
                run.assert_not_called()
            self.assertFalse((root/'outputs').exists())


if __name__ == '__main__':
    unittest.main()
