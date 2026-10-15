import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import nibabel as nib
import numpy as np

from mri_viewer import SliceMRIViewer, SubjectMRIViewer, prepare_subject_image


class SliceViewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / 'image.nii.gz'
        data = np.arange(8*9*10, dtype=np.float32).reshape(8, 9, 10)
        nib.save(nib.Nifti1Image(data, np.diag([-2., 3., 4., 1.])), self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_orientation_sliders_and_window(self):
        viewer = SliceMRIViewer(self.path)
        try:
            self.assertEqual(nib.aff2axcodes(viewer.image.affine), ('R', 'A', 'S'))
            np.testing.assert_array_equal(viewer.data, nib.load(self.path).get_fdata()[::-1])
            self.assertEqual([s.max for s in viewer.sliders], [7, 8, 9])
            self.assertTrue(bytes(viewer.picture.value).startswith(b'\x89PNG'))
            before = bytes(viewer.picture.value)
            viewer.sliders[0].value = 0
            self.assertNotEqual(before, bytes(viewer.picture.value))
            before = bytes(viewer.picture.value)
            viewer.window.value = (0., 350.)
            self.assertNotEqual(before, bytes(viewer.picture.value))
            viewer.sliders[2].value = 9
            self.assertTrue(viewer.picture.value)
        finally:
            viewer.close()
        self.assertIsNone(viewer.data)
        viewer.close()

    def test_invalid_data(self):
        for data in (np.zeros((3, 3, 3)), np.ones((3, 3, 3, 2)),
                     np.full((3, 3, 3), np.nan)):
            nib.save(nib.Nifti1Image(data, np.eye(4)), self.path)
            with self.assertRaises(ValueError):
                SliceMRIViewer(self.path)

    def test_subject_switch_removes_previous_image(self):
        import ipywidgets as w

        class MockNiiVue(w.VBox):
            closed = False

            def __init__(self, height):
                super().__init__()
                self.height = height

            def load_volumes(self, volumes):
                self.volumes = volumes

            def close(self):
                self.closed = True
                super().close()

        directory = self.root / 'subjects' / 'TEST' / 'mri'
        directory.mkdir(parents=True)
        original = nib.load(self.path)
        nib.save(nib.MGHImage(original.get_fdata().astype('float32'), original.affine),
                 directory / 'brain.mgz')
        target = prepare_subject_image('TEST', self.root/'subjects', self.root/'cache')
        np.testing.assert_allclose(nib.load(target).affine, original.affine)
        viewer = SubjectMRIViewer(self.root/'subjects', self.root/'cache')
        with patch('ipyniivue.NiiVue', MockNiiVue):
            viewer.show('TEST')
        old = viewer.viewer
        self.assertIsNotNone(old)
        self.assertEqual(old.height, 480)
        self.assertEqual(old.volumes, [{'path': str(target)}])
        viewer.show('TEST')
        self.assertIs(viewer.viewer, old)
        viewer.show('MISSING')
        self.assertTrue(old.closed)
        self.assertIsNone(viewer.viewer)
        self.assertIsNone(viewer.subject_id)
        self.assertEqual(viewer.box.children, (viewer.status,))
        self.assertIn('unavailable', viewer.status.value)
        viewer.box.close()
        viewer.status.close()


if __name__ == '__main__':
    unittest.main()
