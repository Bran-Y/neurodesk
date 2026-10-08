import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import nibabel as nib
import pandas as pd
from notebook_input import save_case
from user_pipeline import read_config, participants, process, status, analyze
import t2_pipeline


class T2Tests(unittest.TestCase):
    def make_case(self, root):
        source = root/'test.nii.gz'
        nib.save(nib.Nifti1Image(np.ones((8, 8, 8), dtype=np.float32), np.eye(4)), source)
        return read_config(save_case(root, dict(subject_id='T2_TEST', mode='new', modality='T2',
            age='', sex=None, scanner_field_strength='', scanner_manufacturer=None,
            modality_confirmed=True, image_path=str(source))))

    def test_dispatch_and_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.make_case(Path(directory))
            with self.assertRaises(ValueError):
                participants(config)
            self.assertFalse(status(config)[0]['complete'])
            out = t2_pipeline.workdir(config, 'T2_TEST')
            def fake_run(command, **kwargs):
                shell = command[-1]
                self.assertIn('mri_synthseg', shell)
                self.assertIn('mri_synthstrip', shell)
                self.assertNotIn('recon-all', shell)
                mask = np.zeros((8, 8, 8), dtype=np.float32)
                mask[2:6, 2:6, 2:6] = 1
                for name, data in [('brain.nii.gz', mask), ('brain_mask.nii.gz', mask),
                    ('segmentation.nii.gz', mask*17), ('resampled.nii.gz', np.ones_like(mask))]:
                    nib.save(nib.Nifti1Image(data, np.eye(4)), out/name)
                pd.DataFrame([dict(subject='T2_TEST', left_hippocampus=3000)]).to_csv(out/'volumes.csv', index=False)
                pd.DataFrame([dict(subject='T2_TEST', score=.9)]).to_csv(out/'qc.csv', index=False)
            with patch('t2_pipeline.subprocess.run', side_effect=fake_run):
                process(config)
            self.assertTrue(status(config)[0]['complete'])
            with patch('t2_pipeline.preview', return_value='<p>synthetic test preview</p>'):
                reports = analyze(config)
            self.assertIn('No lesion segmentation', reports[0].read_text())
            self.assertIn('3000', reports[0].read_text())
            with self.assertRaises(FileExistsError):
                process(config)
            (out/'volumes.csv').write_text('changed')
            self.assertFalse(status(config)[0]['complete'])
            with self.assertRaises(ValueError):
                analyze(config)

    def test_failure_is_not_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.make_case(Path(directory))
            with patch('t2_pipeline.subprocess.run', side_effect=RuntimeError('missing tool')):
                with self.assertRaises(RuntimeError):
                    process(config)
            self.assertEqual(status(config)[0]['detail']['state'], 'failed')
            with self.assertRaises(ValueError):
                analyze(config)

    def test_invalid_modality_does_not_fall_back_to_t1(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.make_case(Path(directory))
            import json
            raw = json.loads(config['_path'].read_text())
            raw['modality'] = 'FLAIR'
            config['_path'].write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                read_config(config['_path'])


if __name__ == '__main__':
    unittest.main()
