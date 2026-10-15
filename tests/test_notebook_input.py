import tempfile
from pathlib import Path
import unittest
import numpy as np
import nibabel as nib
from notebook_input import save_case
from user_pipeline import read_config, participants


class InputTests(unittest.TestCase):
    def test_upload_config_and_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            src=root/'synthetic.nii.gz'
            nib.save(nib.Nifti1Image(np.ones((3,3,3)),np.eye(4)),src)
            values=dict(mode='new',subject_id='TEST',age=28,sex='Male',scanner_field_strength=1.5,
                        scanner_manufacturer='Siemens',t1_confirmed=True,image_path='')
            config=save_case(root,values,('../../bad.nii.gz',src.read_bytes()))
            row=participants(read_config(config)).iloc[0]
            self.assertTrue(Path(row.t1_path).is_file())
            self.assertEqual(Path(row.t1_path).parent,(root/'cases/TEST').resolve())
            with self.assertRaises(FileExistsError):
                save_case(root,values,('test.nii.gz',src.read_bytes()))

    def test_reject_invalid_without_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            values=dict(mode='new',subject_id='TEST',age=28,sex='Male',scanner_field_strength=1.5,
                        scanner_manufacturer='Siemens',t1_confirmed=True,image_path='')
            with self.assertRaises(Exception):
                save_case(root,values,('invalid.nii.gz',b'not an image'))
            self.assertFalse((root/'cases/TEST').exists())
            with self.assertRaises(ValueError):
                save_case(root,dict(values,subject_id='../escape'))


if __name__=='__main__':
    unittest.main()
