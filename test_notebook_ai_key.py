import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from notebook_ai_key import KEY_ENV, KernelKeyInput


class KeyWidgetTests(unittest.TestCase):
    def setUp(self):
        self.widget = KernelKeyInput()
        self.addCleanup(self.widget.close)

    def test_configure_transient_secret_is_not_returned_or_serialized(self):
        secret = 'synthetic-secret-for-widget-test'
        content = dict(action='configure', key=secret)
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(self.widget, 'send') as send, \
                redirect_stdout(output):
            self.widget._receive(self.widget, content, [])
            self.assertEqual(os.environ[KEY_ENV], secret)
            send.assert_called_once_with(dict(type='key-status', configured=True, error=None))
            self.assertNotIn(secret, json.dumps(self.widget.get_state()))
        self.assertNotIn('key', content)
        self.assertNotIn(secret, output.getvalue())

    def test_status_only_reports_presence_and_never_returns_key(self):
        with patch.dict(os.environ, {KEY_ENV: 'synthetic-existing-secret'}, clear=True), \
                patch.object(self.widget, 'send') as send:
            self.widget._receive(self.widget, {'action': 'status'}, [])
            send.assert_called_once_with(dict(type='key-status', configured=True, error=None))
            self.assertNotIn('synthetic-existing-secret', json.dumps(self.widget.get_state()))

    def test_invalid_input_does_not_replace_existing_key(self):
        for value in (None, '', 'contains whitespace', 123, 'x' * 4097):
            with patch.dict(os.environ, {KEY_ENV: 'synthetic-original'}, clear=True), \
                    patch.object(self.widget, 'send') as send:
                self.widget._receive(self.widget, dict(action='configure', key=value), [])
                self.assertEqual(os.environ[KEY_ENV], 'synthetic-original')
                self.assertEqual(send.call_args.args[0]['error'],
                    'Invalid key. Enter a non-empty key without whitespace.')

    def test_clear_removes_current_kernel_key(self):
        with patch.dict(os.environ, {KEY_ENV: 'synthetic-key'}, clear=True), \
                patch.object(self.widget, 'send') as send:
            self.widget._receive(self.widget, {'action': 'clear'}, [])
            self.assertNotIn(KEY_ENV, os.environ)
            send.assert_called_once_with(dict(type='key-status', configured=False, error=None))

    def test_unknown_message_does_not_modify_environment(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(self.widget, 'send') as send:
            content = dict(action='unexpected', key='synthetic-key')
            self.widget._receive(self.widget, content, [])
            self.assertNotIn(KEY_ENV, os.environ)
            self.assertNotIn('key', content)
            send.assert_not_called()

    def test_frontend_has_no_secret_state_storage_or_network_call(self):
        code = str(self.widget._esm)
        for forbidden in ('model.set(', 'save_changes(', 'localStorage', 'sessionStorage',
                          'fetch(', 'console.log('):
            self.assertNotIn(forbidden, code)
        self.assertIn("field.type = 'password'", code)
        self.assertIn("model.send({ action: 'configure', key })", code)
        self.assertLess(code.index("field.value = '';"), code.index("model.send({ action: 'configure', key })"))


if __name__ == '__main__':
    unittest.main()
