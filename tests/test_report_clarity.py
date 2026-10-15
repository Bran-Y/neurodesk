import unittest

from refresh_pd_pattern_reports import (
    strip_excluded_features_details, strip_exclusion_summary, strip_not_assessed_note,
    strip_repeated_zheng_warnings)
from zheng_exploratory import render as render_zheng


class ReportClarityTests(unittest.TestCase):
    def test_existing_not_assessed_note_is_removed_without_losing_counts_or_details(self):
        html = ('<p>208/249 features assessed; 41 not assessed.</p>'
                '<details><summary>All Potvin measurements</summary>41 excluded rows</details>'
                '<p class="note"><b>Not assessed:</b> No compatible model. '
                'Missing reference coverage must not be interpreted as normality or atrophy.</p>')
        updated = strip_not_assessed_note(html)
        self.assertNotIn('<b>Not assessed:</b>', updated)
        self.assertIn('41 not assessed', updated)
        self.assertIn('41 excluded rows', updated)
        self.assertEqual(strip_not_assessed_note(updated), updated)

    def test_exclusion_summary_is_removed_without_losing_audit_details(self):
        html = ('<p>Evaluated paired measurements: 140.</p>'
                '<p>Exclusion reasons: Missing or duplicate AD/Control reference</p>'
                '<details><summary>Excluded features</summary>'
                'lateral ventricle | lh | roi_volume</details>')
        updated = strip_exclusion_summary(html)
        self.assertNotIn('Exclusion reasons:', updated)
        self.assertIn('Evaluated paired measurements: 140', updated)
        self.assertIn('lateral ventricle | lh | roi_volume', updated)
        self.assertEqual(strip_exclusion_summary(updated), updated)

    def test_excluded_features_panel_is_removed_without_losing_comparisons(self):
        html = ('<p>Evaluated paired measurements: 140.</p>'
                '<details><summary>Per-feature reference-density comparisons</summary>'
                '<table><tr><td>hippocampus</td></tr></table></details>'
                '<details><summary>Excluded features</summary><pre>'
                '[{"feature": "lateral ventricle"}]</pre></details>'
                '<p>Source: Zheng et al. (2023)</p>')
        updated = strip_excluded_features_details(html)
        self.assertNotIn('Excluded features', updated)
        self.assertIn('Evaluated paired measurements: 140', updated)
        self.assertIn('Per-feature reference-density comparisons', updated)
        self.assertIn('hippocampus', updated)
        self.assertIn('Source: Zheng et al.', updated)
        self.assertEqual(strip_excluded_features_details(updated), updated)

    def test_repeated_warnings_are_removed_without_erasing_summary_caveats(self):
        html = ('<p class="note">Age outside the reference cohort: comparisons are extrapolative.</p>'
                '<p role="alert"><b>Age applicability warning: long duplicate.</b></p>'
                '<p role="alert">Research comparison authorised; long duplicate.</p>'
                '<p role="alert">Other warning: keep this.</p>'
                '<p>Evaluated paired measurements: 140.</p>')
        updated = strip_repeated_zheng_warnings(html)
        self.assertNotIn('long duplicate', updated)
        self.assertIn('Age outside the reference cohort', updated)
        self.assertIn('Other warning: keep this.', updated)
        self.assertIn('Evaluated paired measurements: 140', updated)
        self.assertEqual(strip_repeated_zheng_warnings(updated), updated)

    def test_new_zheng_section_does_not_repeat_summary_caveats(self):
        result = dict(subject_id='example', features=[], families=[],
                      warnings=['Age applicability warning: long duplicate.',
                                'Research comparison authorised; long duplicate.',
                                'Other warning: keep this.'])
        content = render_zheng(result)
        self.assertNotIn('long duplicate', content)
        self.assertIn('Other warning: keep this.', content)


if __name__ == '__main__':
    unittest.main()
