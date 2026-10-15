"""Tests for the internal-only weighted evidence analysis."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from weighted_evidence_analysis import PROPOSED_WEIGHTS, analyze_case


def csv_file(path, rows):
    with path.open('w', newline='', encoding='utf-8') as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class WeightedEvidenceAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.subject = 'PPMI_41282'
        prefix = self.subject + '_'
        interpretation = {
            'subject_id': self.subject, 'reference_focus': 'PD',
            'measurement_qc_status': 'unreviewed_qc_skipped_for_report',
            'possible_disease_interpretation': {'pd': {
                'directional_profile': {'assessed': 2,
                    'aligned': [{'normative_status': 'within_95pi'}],
                    'opposed': [{'normative_status': 'within_95pi'}],
                    'at_expected': []},
            }},
        }
        (self.folder / (prefix + 'interpretation.json')).write_text(
            json.dumps(interpretation), encoding='utf-8')
        csv_file(self.folder / (prefix + 'all_potvin_measurements.csv'), [
            {'calculation_status': 'calculated', 'range_status': 'within_95pi'},
            {'calculation_status': 'calculated', 'range_status': 'above_95pi'},
        ])
        csv_file(self.folder / (prefix + 'pd_source_comparisons.csv'), [
            {'match_status': 'matched_for_context'},
            {'match_status': 'matched_for_context'},
        ])
        csv_file(self.folder / (prefix + 'additional_pd_comparisons.csv'), [
            {'comparison_status': 'descriptive_difference', 'paper': 'Mak 2015'},
        ])
        csv_file(self.folder / (prefix + 'source_coverage.csv'), [
            {'used_for_subject_qualitative': '0'},
        ])

    def test_internal_analysis_does_not_write_or_diagnose(self):
        before = {path.name for path in self.folder.iterdir()}
        data = analyze_case(self.folder, self.subject)
        self.assertEqual(before, {path.name for path in self.folder.iterdir()})
        self.assertEqual(sum(PROPOSED_WEIGHTS.values()), 100)
        self.assertIsNone(data['weighted_total'])
        self.assertIsNone(data['disease_probability'])
        self.assertIsNone(data['assigned_diagnosis'])
        self.assertEqual(data['research_tendency'], 'indeterminate')
        self.assertEqual(data['enigma_pd']['aligned_outside_95pi'], 0)

    def test_rejects_other_subject_and_non_pd_scope(self):
        with self.assertRaises(ValueError):
            analyze_case(self.folder, 'PPMI_41289')
        path = self.folder / (self.subject + '_interpretation.json')
        data = json.loads(path.read_text(encoding='utf-8'))
        data['reference_focus'] = 'AD'
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            analyze_case(self.folder, self.subject)


if __name__ == '__main__':
    unittest.main()
