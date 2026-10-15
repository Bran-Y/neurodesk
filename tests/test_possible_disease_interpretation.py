import copy
import unittest

from possible_disease_interpretation import (
    AD_DOI, PD_DOI, INTERPRETATION_SECTION, merge_summary_html, render, summarize)
from test_zheng_age_policy import AgePolicyTest


def pd_row(**changes):
    row = dict(doi=PD_DOI, comparison_group='whole_sample', match_status='matched_for_context',
               direction_eligible=True, review_status='pending_human_review',
               mapping_method='same_native_atlas_label_alignment', normative_status='below_95pi',
               measured=2.1, unit='mm', pd_minus_control_cohen_d=-0.2, p_as_reported='<0.001',
               context='Outside PI in the published group-effect direction; nominal p<0.05 only',
               standard_roi_name='precentral', hemisphere='lh', metric='cortical_thickness',
               source_table='S2a', source_page=6)
    row.update(changes)
    return row


class PossibleDiseaseInterpretationTests(unittest.TestCase):
    def test_ad_reasons_are_four_literature_linked_measurements(self):
        summary = summarize(AgePolicyTest().assess(73))
        self.assertTrue(summary['ad']['candidate'])
        self.assertEqual(len(summary['ad']['reasons']), 4)
        content = render(summary)
        for text in (AD_DOI, 'Zheng et al. (2023)', 'S1 AD / S2 Control',
                     'AD mean +/- SD', 'Higher AD marginal density'):
            self.assertIn(text, content)
        self.assertIsNone(summary['assigned_diagnosis'])
        self.assertIsNone(summary['disease_probabilities'])

    def test_age_warning_does_not_suppress_ad_candidate(self):
        summary = summarize(AgePolicyTest().assess(28))
        self.assertTrue(summary['ad']['candidate'])
        self.assertIn('Age applicability warning', render(summary))

    def test_age_applicable_partial_ad_signal_requires_medical_corroboration(self):
        comparison = AgePolicyTest().assess(73)
        for row in comparison['features']:
            if row['hemisphere'] == 'lh':
                row['closer_density'] = 'Control'
        summary = summarize(comparison)
        self.assertFalse(summary['ad']['candidate'])
        self.assertTrue(summary['ad']['partial_signal'])
        self.assertIn('Partial AD-leaning MRI signal: 2/4', summary['conclusion'])
        self.assertIn('Clinical assessment', summary['conclusion'])
        self.assertIsNone(summary['assigned_diagnosis'])
        content = render(summary, compact=True)
        self.assertIn('Partial AD-reference agreement in hippocampus / rh; amygdala / rh', content)

    def test_out_of_age_two_of_four_does_not_become_ad_leaning(self):
        comparison = AgePolicyTest().assess(28)
        for row in comparison['features']:
            if row['hemisphere'] == 'lh':
                row['closer_density'] = 'Control'
        summary = summarize(comparison)
        self.assertFalse(summary['ad']['partial_signal'])
        self.assertNotIn('AD-leaning', summary['conclusion'])

    def test_compact_report_keeps_short_age_caveat_without_duplicate_warning(self):
        summary = summarize(AgePolicyTest().assess(28))
        content = render(summary, compact=True)
        self.assertIn('Age outside the reference cohort: comparisons are extrapolative', content)
        self.assertNotIn('Age applicability warning:', content)
        self.assertNotIn('Research comparison authorised;', content)

    def test_other_paper_cannot_trigger_zheng_rule(self):
        comparison = AgePolicyTest().assess(73)
        comparison['features'][0]['doi'] = '10.1234/other'
        self.assertFalse(summarize(comparison)['ad']['candidate'])

    def test_pd_like_lists_enigma_and_nominal_significance_limits(self):
        summary = summarize(None, [pd_row()])
        self.assertTrue(summary['pd']['pattern_present'])
        content = render(summary)
        for text in (PD_DOI, 'Laansma et al.', 'precentral / lh', 'S2a, page 6',
                     'corrected significance is not established', 'Potvin'):
            self.assertIn(text, content)
        self.assertIsNone(summary['assigned_diagnosis'])

    def test_ineligible_pd_rows_cannot_trigger_pd_like(self):
        for changes in ({'direction_eligible': False}, {'review_status': 'rejected'},
                        {'match_status': 'unavailable'}, {'comparison_group': 'HY4-5'},
                        {'doi': AD_DOI}, {'normative_status': 'within_95pi'},
                        {'p_as_reported': '0.2'}, {'p_as_reported': None},
                        {'measured': float('nan')}, {'measured': 0},
                        {'pd_minus_control_cohen_d': 0},
                        {'mapping_method': 'not_comparable'},
                        {'context': 'Not comparable: QC exclusion'}):
            with self.subTest(changes=changes):
                self.assertFalse(summarize(None, [pd_row(**changes)])['pd']['pattern_present'])

    def test_opposite_direction_is_retained_not_used_as_support(self):
        summary = summarize(None, [pd_row(pd_minus_control_cohen_d=0.2)])
        self.assertFalse(summary['pd']['pattern_present'])
        self.assertEqual(len(summary['pd']['opposing_features']), 1)
        self.assertIn('Opposite-direction features', render(summary))

    def test_duplicate_and_stage_rows_are_not_independent_votes(self):
        self.assertFalse(summarize(None, [pd_row(), pd_row()])['pd']['pattern_present'])
        summary = summarize(None, [pd_row(), pd_row(comparison_group='HY1')])
        self.assertEqual(len(summary['pd']['reasons']), 1)

    def test_ad_candidate_is_not_relabelled_by_single_pd_direction_match(self):
        summary = summarize(AgePolicyTest().assess(73), [pd_row()])
        self.assertIn('AD-like regional pattern', summary['conclusion'])
        self.assertNotIn('PD-like', summary['conclusion'])
        self.assertTrue(summary['pd']['pattern_present'])
        visible = render(summary, compact=True).split('<details>', 1)[0]
        self.assertIn('AD-like:', visible)
        self.assertNotIn('PD-like:', visible)
        self.assertNotIn('PD-like:', render(summary, compact=True))
        self.assertEqual(summary['pd']['reasons'][0]['standard_roi_name'], 'precentral')
        self.assertIn('does not establish Control', summarize()['conclusion'])

    def test_pd_scope_does_not_run_ad_candidate_rule(self):
        summary = summarize(AgePolicyTest().assess(73), [pd_row()], 'PD')
        self.assertFalse(summary['ad']['candidate'])
        self.assertEqual(summary['ad']['reasons'], [])
        self.assertNotIn('AD-like', render(summary))
        self.assertNotIn('AD-like', render(summary, compact=True))
        self.assertIn('PD-like:', render(summary, compact=True))

    def test_render_escapes_source_fields_without_mutating_results(self):
        summary = summarize(None, [pd_row(standard_roi_name='<script>')])
        before = copy.deepcopy(summary)
        content = render(summary)
        self.assertNotIn('<script>', content)
        self.assertEqual(summary, before)

    def test_compact_summary_has_brief_reasons_and_closed_evidence(self):
        summary = summarize(AgePolicyTest().assess(73), [pd_row()])
        before = copy.deepcopy(summary)
        content = render(summary, compact=True)
        visible = content.split('<details>', 1)[0]
        self.assertNotIn('<h4>', content)
        self.assertNotIn('<table>', visible)
        for text in ('Four-region rule met', 'hippocampus / lh', AD_DOI):
            self.assertIn(text, visible)
        self.assertNotIn('PD-like:', visible)
        self.assertNotIn(PD_DOI, visible)
        self.assertNotIn('precentral / lh', content)
        self.assertNotIn(PD_DOI, content)
        self.assertEqual(summary['pd']['reasons'][0]['source_table'], 'S2a')
        self.assertIn('<details><summary>Interpretation evidence and rules</summary>', content)
        self.assertNotIn('<details open', content)
        self.assertIn('AD mean +/- SD', content)
        self.assertEqual(content.count(summary['conclusion']), 1)
        self.assertEqual(summary, before)

    def test_compact_ad_summary_keeps_pd_evidence_in_record_only(self):
        summary = summarize(AgePolicyTest().assess(28), [pd_row(pd_minus_control_cohen_d=0.2)])
        content = render(summary, compact=True)
        visible = content.split('<details>', 1)[0]
        self.assertIn('age alone does not exclude AD', visible)
        self.assertNotIn('1 opposite-direction features', visible)
        self.assertNotIn('PD-like:', visible)
        self.assertNotIn('Opposite-direction features', content)
        self.assertEqual(len(summary['pd']['opposing_features']), 1)
        self.assertFalse(summary['pd']['pattern_present'])

    def test_compact_pd_only_summary_has_no_ad_source(self):
        content = render(summarize(None, [], 'PD'), compact=True)
        self.assertNotIn('Zheng', content)
        self.assertNotIn(AD_DOI, content)
        self.assertNotIn('AD-like', content)
        self.assertIn('PD-like:', content)

    def test_merge_summary_is_idempotent_and_preserves_existing_content(self):
        summary = summarize(AgePolicyTest().assess(73), [pd_row()])
        base = ('<h4>Demographic</h4><p>Age: 73</p><h4>Summary</h4>'
                '<p>208/249 features assessed: <b>9 below, 196 within, 3 above</b>.</p>'
                '<h4>Quantitative / Potvin: highlighted deviations</h4><p>2594.9</p>')
        old = base.replace('<h4>Summary</h4>', render(summary) + '<h4>Summary</h4>')
        merged = merge_summary_html(old, summary)
        self.assertEqual(INTERPRETATION_SECTION.sub('', merged), base)
        self.assertEqual(merge_summary_html(merged, summary), merged)
        self.assertEqual(merged.count('<h4>Summary</h4>'), 1)
        self.assertNotIn('<h4>Possible Disease Interpretation</h4>', merged)
        self.assertLess(merged.index('208/249'), merged.index('Possible disease interpretation:'))
        self.assertLess(merged.index('data-summary-layout="merged"'), merged.index('<h4>Quantitative'))

    def test_merge_rejects_missing_duplicate_or_reversed_sections(self):
        for content in ('<h4>Summary</h4><p>counts</p>',
                        '<h4>Demographic</h4><h4>Summary</h4><h4>Summary</h4><p>counts</p>',
                        '<h4>Summary</h4><p>counts</p><h4>Demographic</h4>',
                        '<h4>Demographic</h4><h4>Summary</h4>'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                merge_summary_html(content, summarize())

    def test_compact_region_names_are_escaped(self):
        content = render(summarize(None, [pd_row(standard_roi_name='<script>')]), compact=True)
        self.assertNotIn('<script>', content)
        self.assertIn('&lt;script&gt;', content)


if __name__ == '__main__':
    unittest.main()
