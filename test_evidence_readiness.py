import unittest
from evidence_readiness import compatibility


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.patient = dict(roi_name='Left-Hippocampus', hemisphere='lh', imaging_metric='roi_volume',
            unit='mm3', atlas_name='aseg', processing_software_version='5.3.0', normalization_method='raw', age=73)
        self.reference = dict(self.patient, human_review_status='accepted', comparison_compatible=True,
            roi_boundary_verified=True, reference_age_min=60, reference_age_max=90)

    def test_complete_and_boundary(self):
        self.assertEqual(compatibility(self.patient, self.reference), [])
        for age in (60, 90):
            self.assertEqual(compatibility(dict(self.patient, age=age), self.reference), [])

    def test_each_gate(self):
        for field, value in [('unit', 'cm3'), ('hemisphere', 'rh'), ('atlas_name', 'DKT'),
                             ('processing_software_version', None), ('normalization_method', None),
                             ('age', 18), ('age', float('nan'))]:
            self.assertTrue(compatibility(dict(self.patient, **{field: value}), self.reference), field)
        for field, value in [('human_review_status', 'rejected'), ('comparison_compatible', False),
                             ('roi_boundary_verified', False)]:
            self.assertTrue(compatibility(self.patient, dict(self.reference, **{field: value})))


if __name__ == '__main__':
    unittest.main()
