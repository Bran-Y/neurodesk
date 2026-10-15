import unittest
import tempfile
from pathlib import Path
import pandas as pd
from exploratory_pd_no_qc import unfiltered_copy, metadata
from possible_disease_interpretation import summarize


class ExploratoryTests(unittest.TestCase):
    def test_identifier_xml_is_not_additional_patient_or_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'detailed.xml').write_text('<idaxs xmlns="test"><project xmlns=""><subject>'
                '<subjectIdentifier>41289</subjectIdentifier><researchGroup>PD</researchGroup>'
                '<study><imagingProtocol><imageUID>643386</imageUID><protocolTerm>'
                '<protocol term="Field Strength">0.0</protocol></protocolTerm>'
                '</imagingProtocol></study></subject></project></idaxs>')
            (root / 'id.xml').write_text('<metadata><subject id="41289"/><image uid="I643386"/></metadata>')
            data = metadata(root)
            self.assertEqual(data['unique_scan_records'], 1)
            self.assertEqual(data['xml_files'], 2)
            self.assertEqual(data['records'][0]['protocol_terms']['Field Strength'], '0.0')

    def test_only_qc_reason_removed_and_original_unchanged(self):
        frame = pd.DataFrame([dict(value_numeric=10., qc_hold_reason='pending boundary',
                                   comparison_mapping_error='wrong atlas', unit='mm3',
                                   processing_software_version='5.3', research_group='PD')])
        before = frame.copy(deep=True)
        clean = unfiltered_copy(frame)
        self.assertNotIn('qc_hold_reason', clean)
        self.assertEqual(clean.loc[0, 'comparison_mapping_error'], 'wrong atlas')
        clean.loc[0, 'value_numeric'] = 20.
        pd.testing.assert_frame_equal(frame, before)

    def test_no_forced_pd_diagnosis_when_no_eligible_measurement(self):
        interpretation = summarize(pd_rows=[], scope='PD')
        self.assertIsNone(interpretation['assigned_diagnosis'])
        self.assertFalse(interpretation['pd']['pattern_present'])
        self.assertFalse(interpretation['known_diagnosis_used_as_input'])


if __name__ == '__main__':
    unittest.main()
