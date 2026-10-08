import copy
from contextlib import redirect_stdout
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import ai_evidence_assistant as ai


def synthetic_payload():
    """Wholly fabricated data for transport/schema tests, not a medical example."""
    return dict(schema_version=1, case_alias='synthetic_test_only', demographics={},
        measurement_counts={'within_95pi': 1},
        evidence=[dict(evidence_id='N0001', kind='normative_comparison', source='Potvin',
            roi_name='synthetic_roi', observed_value=2.5, expected_value=2.6,
            lower_95pi=2.0, upper_95pi=3.2, unit='mm', calculation_status='calculated',
            range_status='within_95pi', comparable=True)],
        sources={'Potvin': ai.SOURCES['Potvin']},
        scope='Fabricated transport test. No PD or AD group evidence exists.',
        limitations=['Synthetic data; not an actual patient or a paper-derived interval.'])


def synthetic_answer():
    return dict(summary='The fabricated normative measurement cannot identify a disease.',
        findings=[dict(interpretation='The supplied measurement is within its reference range.', evidence_ids=['N0001'])],
        candidate_discussion=[dict(condition='PD', status='insufficient_evidence',
            supporting_evidence_ids=[], opposing_evidence_ids=[],
            caveat='No disease-specific comparison is supplied; normal imaging does not exclude this condition.')],
        missing_information=['Disease-specific comparison data and clinical assessment'])


def synthetic_pd_payload():
    payload = synthetic_payload()
    payload['sources']['ENIGMA_PD'] = ai.SOURCES['ENIGMA_PD']
    payload['evidence'].append(dict(evidence_id='PD0001', source='ENIGMA_PD',
        kind='group_effect_context', comparable=True, measured=2.0,
        normative_status='below_95pi', pd_minus_control_cohen_d=-0.2))
    return payload


def synthetic_possible_pd():
    answer = synthetic_answer()
    answer['summary'] = 'Possible PD is an exploratory hypothesis, not a diagnosis.'
    answer['candidate_discussion'][0].update(status='possible_association',
        supporting_evidence_ids=['PD0001'],
        caveat='A measured deviation aligns with the published group pattern, which lacks diagnostic specificity.')
    return answer


class FakeOpener:
    def __init__(self, answer=None, model='glm-5.3-flash', finish='stop'):
        self.answer, self.model, self.finish = answer or synthetic_answer(), model, finish
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        return io.BytesIO(json.dumps(dict(model=self.model, choices=[dict(finish_reason=self.finish,
            message={'content': json.dumps(self.answer)})], usage=dict(prompt_tokens=1, completion_tokens=1,
            total_tokens=2))).encode())


class AITests(unittest.TestCase):
    def test_configure_key_uses_hidden_input_and_never_prints_value(self):
        output = io.StringIO()
        with patch.dict(ai.os.environ, {}, clear=True), \
                patch('ai_credentials.load_api_key', return_value=False), \
                patch.object(ai.getpass, 'getpass', return_value='synthetic-key-only') as prompt, \
                redirect_stdout(output):
            ai.configure_api_key()
            self.assertEqual(ai.os.environ[ai.KEY_ENV], 'synthetic-key-only')
            prompt.assert_called_once()
        self.assertNotIn('synthetic-key-only', output.getvalue())
        self.assertIn('No request sent', output.getvalue())

    def test_configured_kernel_does_not_ask_for_key_again(self):
        with patch.dict(ai.os.environ, {ai.KEY_ENV: 'synthetic-key-only'}, clear=True), \
                patch.object(ai.getpass, 'getpass') as prompt, redirect_stdout(io.StringIO()):
            ai.configure_api_key()
            prompt.assert_not_called()
            self.assertEqual(ai.os.environ[ai.KEY_ENV], 'synthetic-key-only')

    def test_key_can_be_replaced_explicitly(self):
        with patch.dict(ai.os.environ, {ai.KEY_ENV: 'synthetic-old-key'}, clear=True), \
                patch.object(ai.getpass, 'getpass', return_value='synthetic-new-key') as prompt, \
                redirect_stdout(io.StringIO()):
            ai.configure_api_key(force=True)
            prompt.assert_called_once()
            self.assertEqual(ai.os.environ[ai.KEY_ENV], 'synthetic-new-key')

    def test_selected_model_and_no_key_in_settings(self):
        cfg = ai.settings()
        self.assertEqual(cfg['model'], 'glm-5.3-flash')
        self.assertEqual(set(cfg), set(ai.DEFAULTS))

    def test_consent_before_any_network(self):
        transport = FakeOpener()
        with self.assertRaises(ai.AIError):
            ai.explain(synthetic_payload(), api_key='test-only', opener=transport)
        self.assertEqual(transport.calls, [])

    def test_valid_response_and_secret_not_in_audit(self):
        transport = FakeOpener()
        result = ai.explain(synthetic_payload(), consent=True, api_key='test-only', opener=transport)
        sent = json.loads(transport.calls[0].data)
        self.assertEqual(sent['model'], 'glm-5.3-flash')
        self.assertEqual(sent['reasoning_effort'], 'low')
        self.assertEqual(sent['response_format'], {'type': 'json_object'})
        self.assertNotIn('test-only', json.dumps(result))
        self.assertNotIn('test-only', transport.calls[0].data.decode())
        self.assertEqual(result['audit']['payload_sha256'], ai.payload_hash(synthetic_payload()))
        self.assertIsNone(result['audit']['diagnosis_probability'])
        self.assertEqual(result['audit']['requested_reasoning_effort'], 'low')
        self.assertGreaterEqual(result['audit']['elapsed_seconds'], 0)
        self.assertIn(ai.SOURCES['Potvin'], ai.render_explanation(result, synthetic_payload()))

    def test_unknown_citation_and_unavailable_vote_rejected(self):
        answer = synthetic_answer()
        answer['findings'][0]['evidence_ids'] = ['invented']
        with self.assertRaises(ai.AIError):
            ai.validate_answer(answer, synthetic_payload())
        answer = synthetic_answer()
        answer['candidate_discussion'][0]['supporting_evidence_ids'] = ['N0001']
        payload = synthetic_payload()
        payload['evidence'][0]['comparable'] = False
        with self.assertRaises(ai.AIError):
            ai.validate_answer(answer, payload)

    def test_model_mismatch_and_truncation_rejected(self):
        for transport in (FakeOpener(model='different'), FakeOpener(finish='length')):
            with self.assertRaises(ai.AIError):
                ai.explain(synthetic_payload(), consent=True, api_key='test-only', opener=transport)

    def test_numeric_claims_and_diagnostic_grade_rejected(self):
        for text in ('PD probability is 90%', 'The most likely disease is PD'):
            answer = synthetic_answer()
            answer['summary'] = text
            with self.assertRaises(ai.AIError):
                ai.validate_answer(answer, synthetic_payload())
        answer['summary'] = 'Evidence is limited.'
        answer['candidate_discussion'][0]['status'] = 'high_support'
        with self.assertRaises(ai.AIError):
            ai.validate_answer(answer, synthetic_payload())

    def test_possible_pd_is_accepted_and_shown_with_source(self):
        payload, answer = synthetic_pd_payload(), synthetic_possible_pd()
        transport = FakeOpener(answer=answer)
        response = ai.explain(payload, consent=True, api_key='test-only', opener=transport)
        report = ai.render_explanation(response, payload)
        self.assertIn('Possible PD (exploratory association)', report)
        self.assertIn('PD0001', report)
        self.assertIn(ai.SOURCES['ENIGMA_PD'], report)
        self.assertLess(report.index('Possible PD (exploratory association)'), report.index('<details>'))

    def test_model_receives_exact_precomputed_candidate_context(self):
        payload = synthetic_pd_payload()
        payload['evidence'].append(dict(payload['evidence'][-1], evidence_id='PD0002',
                                        normative_status='above_95pi'))
        wire = ai.outbound_payload(payload)
        self.assertEqual(wire['candidate_context_eligibility']['PD'], {
            'supporting_evidence_ids': ['PD0001'], 'opposing_evidence_ids': ['PD0002']})
        self.assertEqual(wire['candidate_context_eligibility']['AD'], {
            'supporting_evidence_ids': [], 'opposing_evidence_ids': []})
        restored = []
        for table in wire['evidence_tables']:
            flags = table.get('present', [[True] * len(table['columns'])] * len(table['rows']))
            for values, present in zip(table['rows'], flags):
                restored.append({**table['common'], **{key: value for key, value, keep
                    in zip(table['columns'], values, present) if keep}})
        self.assertEqual(restored, payload['evidence'])

    def test_pd_mixed_evidence_is_no_longer_categorically_rejected(self):
        payload, answer = synthetic_pd_payload(), synthetic_possible_pd()
        payload['evidence'].append(dict(payload['evidence'][-1], evidence_id='PD0002',
                                        normative_status='above_95pi'))
        answer['candidate_discussion'][0].update(status='mixed_evidence',
                                                opposing_evidence_ids=['PD0002'])
        answer['summary'] = 'The directional evidence is mixed, not a disease attribution.'
        self.assertEqual(ai.validate_answer(answer, payload), answer)
        report = ai.render_explanation({'answer': answer}, payload)
        self.assertIn('PD reference comparison: mixed evidence', report)
        self.assertIn('Insufficient for disease attribution.', report)
        self.assertNotIn('Possible PD', report)
        self.assertIn('PD0002', report)

    def test_mixed_ad_control_are_not_rendered_as_disease_or_health_candidates(self):
        payload = synthetic_payload()
        payload['sources']['Zheng_AD_Control'] = ai.SOURCES['Zheng_AD_Control']
        for eid, closer in (('AD0008', 'AD'), ('AD0123', 'Control')):
            payload['evidence'].append(dict(evidence_id=eid, source='Zheng_AD_Control',
                kind='exploratory_marginal_comparison', comparable=True, observed=2.0,
                closer_density=closer, atypical_both=False))
        for condition, support, oppose in (('AD', 'AD0008', 'AD0123'),
                                           ('Control', 'AD0123', 'AD0008')):
            with self.subTest(condition=condition):
                answer = synthetic_answer()
                answer['candidate_discussion'][0].update(condition=condition,
                    status='mixed_evidence', supporting_evidence_ids=[support],
                    opposing_evidence_ids=[oppose], caveat='The regional comparisons disagree.')
                before = copy.deepcopy(answer)
                report = ai.render_explanation({'answer': answer}, payload)
                self.assertIn(condition + ' reference comparison: mixed evidence', report)
                self.assertIn('Insufficient for disease attribution.', report)
                self.assertNotIn('Possible AD', report)
                self.assertNotIn('Control-like pattern', report)
                self.assertIn('Zheng_AD_Control [AD0008]', report)
                self.assertIn('Zheng_AD_Control [AD0123]', report)
                self.assertEqual(answer, before)

    def test_pd_neutral_missing_and_unmatched_rows_are_not_support(self):
        for changes in ({'normative_status': 'within_95pi'},
                        {'normative_status': 'not_calculated'},
                        {'pd_minus_control_cohen_d': 0},
                        {'pd_minus_control_cohen_d': float('nan')},
                        {'comparable': False}, {'measured': None},
                        {'normative_status': 'above_95pi'}):
            with self.subTest(changes=changes):
                payload = synthetic_pd_payload()
                payload['evidence'][-1].update(changes)
                with self.assertRaises(ai.AIError):
                    ai.validate_answer(synthetic_possible_pd(), payload)

    def test_normal_mri_cannot_be_used_as_opposition_to_pd(self):
        payload, answer = synthetic_pd_payload(), synthetic_possible_pd()
        payload['evidence'].append(dict(payload['evidence'][-1], evidence_id='PD0002',
                                        normative_status='within_95pi'))
        answer['candidate_discussion'][0].update(status='mixed_evidence',
                                                opposing_evidence_ids=['PD0002'])
        with self.assertRaises(ai.AIError):
            ai.validate_answer(answer, payload)

    def test_possible_association_cannot_hide_opposing_context(self):
        payload = synthetic_pd_payload()
        payload['evidence'].append(dict(payload['evidence'][-1], evidence_id='PD0002',
                                        normative_status='above_95pi'))
        with self.assertRaises(ai.AIError):
            ai.validate_answer(synthetic_possible_pd(), payload)

    def test_possible_association_requires_support(self):
        answer = synthetic_possible_pd()
        answer['candidate_discussion'][0]['supporting_evidence_ids'] = []
        with self.assertRaises(ai.AIError):
            ai.validate_answer(answer, synthetic_pd_payload())

    def test_ad_control_follow_same_candidate_contract_without_age_cutoff(self):
        payload = synthetic_payload()
        payload['sources']['Zheng_AD_Control'] = ai.SOURCES['Zheng_AD_Control']
        payload['evidence'].append(dict(evidence_id='AD0001', source='Zheng_AD_Control',
            kind='exploratory_marginal_comparison', comparable=True, observed=2.0,
            closer_density='AD', atypical_both=False, age_applicable=False))
        for condition in ('AD', 'Control'):
            with self.subTest(condition=condition):
                payload['evidence'][-1]['closer_density'] = condition
                answer = synthetic_answer()
                answer['candidate_discussion'][0].update(condition=condition,
                    status='possible_association', supporting_evidence_ids=['AD0001'])
                self.assertEqual(ai.validate_answer(answer, payload), answer)
        payload['evidence'][-1]['atypical_both'] = True
        with self.assertRaises(ai.AIError):
            ai.validate_answer(answer, payload)

    def test_prompt_update_invalidates_old_cache_without_deleting_it(self):
        from automatic_ai_report import ReportCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = ReportCache(tmp, ai.settings())
            payload = synthetic_pd_payload()
            with patch.object(ai, 'PROMPT_VERSION', 'evidence-explanation-v4-compact-json-low'):
                old_path = cache.path('synthetic', payload)
            self.assertNotEqual(old_path, cache.path('synthetic', payload))

    def test_html_is_escaped(self):
        answer = synthetic_answer()
        answer['summary'] = '<script>alert("bad")</script>'
        output = ai.render_explanation({'answer': answer}, synthetic_payload())
        self.assertNotIn('<script>', output)
        self.assertIn('&lt;script&gt;', output)

    def test_missing_norms_show_verified_status_not_ai_normality_claim(self):
        payload, answer = synthetic_payload(), synthetic_answer()
        payload['evidence'][0].update(calculation_status='not_calculated', comparable=False)
        answer['findings'][0]['interpretation'] = 'The hippocampus is within its normative interval.'
        before = copy.deepcopy(answer)
        output = ai.render_explanation({'answer': answer}, payload)
        self.assertNotIn('The hippocampus is within', output)
        self.assertIn('AI interpretation withheld for review', output)
        self.assertIn('not assessed', output)
        self.assertIn(ai.SOURCES['Potvin'], output)
        self.assertEqual(answer, before)

    def test_redaction_and_subject_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [dict(subject_id='private_subject', diagnosis='secret_PD_label',
                source_file='/private/name/brain.mgz', clinical_note='private_note',
                age=60, sex='Male', scanner_field_strength=3, scanner_manufacturer='Siemens',
                processing_software_version='5.3.0', estimated_total_intracranial_volume=1500000),
                dict(subject_id='other_private_subject', age=20)]
            norm = dict(subject_id='private_subject', roi_name='entorhinal', hemisphere='lh',
                imaging_metric='cortical_thickness', observed_value=2.5, expected_value=2.6,
                lower_95pi=2.0, upper_95pi=3.2, calculation_status='calculated',
                range_status='within_95pi', unit='mm', source_file='/private/name/stats')
            r = dict(features=pd.DataFrame(rows), normative=pd.DataFrame([norm]), project_dir=tmp)
            with patch('comparison_atlas.comparison_features', return_value=r['features']), \
                    patch('pd_evidence.compare_result', return_value=[]):
                payload = ai.build_payload(r, 'private_subject')
            text = ai.serialise(payload)
            for forbidden in ('private_subject', 'secret_PD_label', '/private/', 'private_note'):
                self.assertNotIn(forbidden, text)
            self.assertEqual(payload['measurement_counts'], {'within_95pi': 1})

    def test_subject_switch_clears_response_and_consent(self):
        import ipywidgets as w
        subject = w.Dropdown(options=['case_a', 'case_b'])
        panel = ai.AIEvidencePanel({}, subject)
        panel.payload = synthetic_payload()
        panel.prepared_subject = subject.value
        panel.consent.value = True
        panel.response = {'answer': synthetic_answer()}
        panel.output.value = 'case_a output'
        subject.value = 'case_b'
        self.assertFalse(panel.consent.value)
        self.assertTrue(panel.send.disabled)
        self.assertIsNone(panel.response)
        self.assertIsNone(panel.payload)
        self.assertEqual(panel.output.value, '')

    def test_report_first_ui_never_prepares_or_sends_automatically(self):
        import ipywidgets as w
        subject = w.Dropdown(options=['case_a', 'case_b'])
        with patch.object(ai, 'build_payload') as build, patch.object(ai, 'explain') as explain:
            panel = ai.AIEvidencePanel({}, subject)
            subject.value = 'case_b'
            panel.generate()
            build.assert_not_called()
            explain.assert_not_called()
        self.assertIsInstance(panel.box, w.VBox)
        self.assertFalse(hasattr(panel, 'preview'))
        self.assertFalse(hasattr(panel, 'prepare'))
        self.assertFalse(panel.consent.disabled)
        self.assertTrue(panel.send.disabled)

    def test_one_click_generation_keeps_payload_out_of_widgets(self):
        import ipywidgets as w
        subject = w.Dropdown(options=['case_a', 'case_b'], value='case_b')
        panel = ai.AIEvidencePanel({}, subject)
        payload = synthetic_payload()
        response = {'answer': synthetic_answer()}
        panel.consent.value = True
        with patch.object(ai, 'build_payload', return_value=payload) as build, \
                patch.object(ai, 'explain', return_value=response) as explain:
            panel.generate()
            build.assert_called_once_with({}, 'case_b')
            explain.assert_called_once_with(payload, consent=True, config=panel.config)
        self.assertEqual(panel.prepared_subject, 'case_b')
        self.assertEqual(panel.payload, payload)
        self.assertIn('AI report', panel.output.value)
        self.assertIn(ai.SOURCES['Potvin'], panel.output.value)
        self.assertNotIn('<pre', panel.output.value)
        self.assertNotIn('href="#ai-', panel.output.value)
        self.assertFalse(panel.consent.value)
        self.assertTrue(panel.send.disabled)
        self.assertFalse(panel.save.disabled)
        def widget_text(widget):
            value = getattr(widget, 'value', '')
            return (value if isinstance(value, str) else '') + ''.join(
                widget_text(child) for child in getattr(widget, 'children', ()))
        for raw_field in ('schema_version', 'observed_value', 'preview bytes'):
            self.assertNotIn(raw_field, widget_text(panel.box))
        self.assertIn('synthetic_roi', widget_text(panel.box))
        self.assertIn('<details><summary>Verified values behind AI citations</summary>', widget_text(panel.box))

    def test_saved_html_is_clean_and_json_retains_audit(self):
        import ipywidgets as w
        with tempfile.TemporaryDirectory() as tmp:
            panel = ai.AIEvidencePanel({'output_dir': tmp}, w.Dropdown(options=['case_a']))
            panel.payload = synthetic_payload()
            panel.response = {'answer': synthetic_answer(), 'audit': {'test_only': True}}
            panel.prepared_subject = 'case_a'
            panel.save_draft()
            path = next((Path(tmp) / 'ai_explanations').glob('*.json'))
            self.assertEqual(json.loads(path.read_text())['evidence_payload'], panel.payload)
            report = path.with_suffix('.html').read_text()
            self.assertIn(ai.SOURCES['Potvin'], report)
            self.assertNotIn('<pre', report)
            self.assertNotIn('observed_value', report)

    def test_changed_subject_during_generation_discards_old_report(self):
        import ipywidgets as w
        subject = w.Dropdown(options=['case_a', 'case_b'])
        panel = ai.AIEvidencePanel({}, subject)
        panel.consent.value = True
        def switch_subject(*args, **kwargs):
            subject.value = 'case_b'
            return {'answer': synthetic_answer()}
        with patch.object(ai, 'build_payload', return_value=synthetic_payload()), \
                patch.object(ai, 'explain', side_effect=switch_subject):
            panel.generate()
        self.assertIsNone(panel.response)
        self.assertIsNone(panel.payload)
        self.assertIn('discarded', panel.output.value)
        self.assertTrue(panel.save.disabled)
        self.assertFalse(panel.consent.value)
        self.assertFalse(subject.disabled)

    def test_payload_error_does_not_send_or_leave_controls_locked(self):
        import ipywidgets as w
        subject = w.Dropdown(options=['case_a'])
        panel = ai.AIEvidencePanel({}, subject)
        panel.consent.value = True
        with patch.object(ai, 'build_payload', side_effect=ValueError('bad data')), \
                patch.object(ai, 'explain') as explain:
            panel.generate()
            explain.assert_not_called()
        self.assertIsNone(panel.response)
        self.assertFalse(panel.busy)
        self.assertFalse(subject.disabled)
        self.assertFalse(panel.consent.disabled)
        self.assertFalse(panel.consent.value)
        self.assertTrue(panel.save.disabled)

    def test_redirect_does_not_forward_credentials(self):
        with self.assertRaises(ai.AIError):
            ai._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test')


if __name__ == '__main__':
    unittest.main()
