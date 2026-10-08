import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ipywidgets as w
import ai_evidence_assistant as ai
from automatic_ai_report import AutomaticAIPanel, ReportCache, policy
from test_ai_evidence_assistant import FakeOpener, synthetic_payload


def enable(root):
    data = json.loads((Path(__file__).parent / 'ai_report_policy.json').read_text())
    (Path(root) / 'ai_report_policy.json').write_text(json.dumps(data))


def fake_response():
    return ai.explain(synthetic_payload(), consent=True, api_key='synthetic-test-only',
                      opener=FakeOpener())


class AutomaticTests(unittest.TestCase):
    def test_columnar_roundtrip_keeps_all_rows_nulls_and_values(self):
        payload = synthetic_payload()
        payload['evidence'].append({**payload['evidence'][0], 'evidence_id': 'N0002',
                                    'optional': None, 'observed_value': 1.8})
        payload['evidence'][0]['optional_other'] = False
        encoded = ai.outbound_payload(payload)
        restored = []
        for table in encoded['evidence_tables']:
            flags = table.get('present', [[True] * len(table['columns'])] * len(table['rows']))
            for row, present in zip(table['rows'], flags):
                restored.append({**table['common'], **dict(
                    (key, value) for key, value, exists in zip(table['columns'], row, present) if exists)})
        self.assertEqual(restored, payload['evidence'])
        self.assertEqual(encoded['demographics'], payload['demographics'])

    def test_repeated_view_reuses_saved_report_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            enable(tmp)
            cache = ReportCache(tmp, dict(ai.DEFAULTS))
            payload, response = synthetic_payload(), fake_response()
            with patch('ai_credentials.load_api_key', return_value=True), \
                    patch.object(ai, 'explain', return_value=response) as explain:
                first = cache.generate('case_a', payload)
                second = cache.generate('case_a', payload)
                explain.assert_called_once()
            self.assertEqual(first, second)
            self.assertEqual(first['status'], 'complete')
            path = cache.path('case_a', payload)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertIn(ai.SOURCES['Potvin'], path.with_suffix('.html').read_text())
            self.assertNotIn('synthetic-test-only', path.read_text())

    def test_failed_call_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            enable(tmp)
            cache = ReportCache(tmp, dict(ai.DEFAULTS))
            with patch('ai_credentials.load_api_key', return_value=True), \
                    patch.object(ai, 'explain', side_effect=ai.AIError('Timed out')) as explain:
                self.assertEqual(cache.generate('case_a', synthetic_payload())['status'], 'failed')
                self.assertEqual(cache.generate('case_a', synthetic_payload())['status'], 'failed')
                explain.assert_called_once()

    def test_cache_hit_refreshes_html_without_network_or_audit_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            enable(tmp)
            cache = ReportCache(tmp, dict(ai.DEFAULTS))
            payload = synthetic_payload()
            with patch('ai_credentials.load_api_key', return_value=True), \
                    patch.object(ai, 'explain', return_value=fake_response()):
                first = cache.generate('case_a', payload)
            path = cache.path('case_a', payload)
            original_audit = path.read_bytes()
            path.with_suffix('.html').write_text('stale presentation')
            with patch.object(ai, 'explain') as explain, \
                    patch('ai_credentials.load_api_key') as credentials:
                second = cache.generate('case_a', payload)
                explain.assert_not_called()
                credentials.assert_not_called()
            self.assertEqual(first, second)
            self.assertEqual(path.read_bytes(), original_audit)
            report = path.with_suffix('.html').read_text()
            self.assertNotIn('stale presentation', report)
            self.assertIn('AI synthesis (unreviewed)', report)
            self.assertEqual(path.with_suffix('.html').stat().st_mode & 0o777, 0o600)

    def test_pending_call_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            enable(tmp)
            cache = ReportCache(tmp, dict(ai.DEFAULTS))
            def during_request(*args, **kwargs):
                self.assertEqual(cache.generate('case_a', synthetic_payload())['status'], 'pending')
                return fake_response_value
            fake_response_value = fake_response()
            with patch('ai_credentials.load_api_key', return_value=True), \
                    patch.object(ai, 'explain', side_effect=during_request) as explain:
                self.assertEqual(cache.generate('case_a', synthetic_payload())['status'], 'complete')
                explain.assert_called_once()

    def test_policy_disabled_or_invalid_never_sends(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ai, 'explain') as explain:
            cache = ReportCache(tmp, dict(ai.DEFAULTS))
            for contents in ('null', 'not-json', '{"auto_generate":false}'):
                (Path(tmp) / 'ai_report_policy.json').write_text(contents)
                self.assertFalse(policy(tmp))
                with self.assertRaises(ai.AIError):
                    cache.generate('case_a', synthetic_payload())
            explain.assert_not_called()

    def test_changed_evidence_subject_or_model_settings_gets_distinct_key(self):
        cache = ReportCache('.', dict(ai.DEFAULTS))
        payload = synthetic_payload()
        first = cache.path('a', payload)
        self.assertNotEqual(first, cache.path('b', payload))
        changed = copy.deepcopy(payload)
        changed['evidence'][0]['observed_value'] = 2.8
        self.assertNotEqual(first, cache.path('a', changed))
        cache.config['max_tokens'] += 1
        self.assertNotEqual(first, cache.path('a', payload))

    def test_invalid_cached_citation_cannot_be_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            enable(tmp)
            cache = ReportCache(tmp, dict(ai.DEFAULTS))
            with patch('ai_credentials.load_api_key', return_value=True), \
                    patch.object(ai, 'explain', return_value=fake_response()):
                cache.generate('case_a', synthetic_payload())
            path = cache.path('case_a', synthetic_payload())
            data = json.loads(path.read_text())
            data['response']['answer']['findings'][0]['evidence_ids'] = ['invented']
            path.write_text(json.dumps(data))
            with patch.object(ai, 'explain') as explain:
                with self.assertRaises(ai.AIError):
                    cache.generate('case_a', synthetic_payload())
                explain.assert_not_called()


class AutomaticUITests(unittest.IsolatedAsyncioTestCase):
    async def test_show_has_no_generate_button_and_renders_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            enable(tmp)
            panel = AutomaticAIPanel({'project_dir': tmp}, w.Dropdown(options=['case_a']))
            self.assertFalse(any(isinstance(child, w.Button) for child in panel.box.children))
            with patch.object(ai, 'build_payload', return_value=synthetic_payload()), \
                    patch.object(panel.cache, 'generate', return_value={'status': 'complete', 'response': fake_response()}) as generate:
                panel.start()
                await asyncio.gather(*panel._tasks)
                generate.assert_called_once()
            self.assertEqual(panel.prepared_subject, 'case_a')
            self.assertIn('AI synthesis (unreviewed)', panel.output.value)
            self.assertIn(ai.SOURCES['Potvin'], panel.output.value)

    async def test_fast_subject_switch_avoids_dispatch_for_old_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            enable(tmp)
            subject = w.Dropdown(options=['case_a', 'case_b'])
            panel = AutomaticAIPanel({'project_dir': tmp}, subject)
            with patch.object(ai, 'build_payload', return_value=synthetic_payload()), \
                    patch.object(panel.cache, 'generate', return_value={'status': 'complete', 'response': fake_response()}) as generate:
                panel.start()
                subject.value = 'case_b'
                panel.start()
                await asyncio.gather(*panel._tasks)
                generate.assert_called_once_with('case_b', synthetic_payload())
            self.assertEqual(panel.prepared_subject, 'case_b')
            self.assertNotIn('case_a', panel.output.value)

    async def test_previous_patient_response_cannot_replace_new_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            enable(tmp)
            subject = w.Dropdown(options=['case_a', 'case_b'])
            panel = AutomaticAIPanel({'project_dir': tmp}, subject)
            def response_after_switch(*args):
                subject.value = 'case_b'
                return {'status': 'complete', 'response': fake_response_value}
            fake_response_value = fake_response()
            with patch.object(ai, 'build_payload', return_value=synthetic_payload()), \
                    patch.object(panel.cache, 'generate', side_effect=response_after_switch):
                panel.start()
                await asyncio.gather(*panel._tasks)
            self.assertIsNone(panel.response)
            self.assertNotIn('AI synthesis (unreviewed)', panel.output.value)

    async def test_close_before_dispatch_sends_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            enable(tmp)
            panel = AutomaticAIPanel({'project_dir': tmp}, w.Dropdown(options=['case_a']))
            with patch.object(panel.cache, 'generate') as generate:
                panel.start()
                panel.close()
                await asyncio.gather(*panel._tasks)
                generate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
