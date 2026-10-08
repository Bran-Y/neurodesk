import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import ai_credentials as credentials
import ai_evidence_assistant as ai
from test_ai_evidence_assistant import FakeOpener, synthetic_payload


class CredentialTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / '.env'

    def test_private_file_loads_after_a_fresh_environment_without_printing_secret(self):
        output = io.StringIO()
        with redirect_stdout(output):
            credentials.save_api_key('synthetic-env-key', self.path)
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
            with patch.dict(os.environ, {}, clear=True):
                self.assertIs(credentials.load_api_key(self.path), True)
                self.assertEqual(os.environ[credentials.KEY_ENV], 'synthetic-env-key')
        self.assertNotIn('synthetic-env-key', output.getvalue())

    def test_existing_kernel_key_is_not_overwritten(self):
        credentials.save_api_key('synthetic-file-key', self.path)
        with patch.dict(os.environ, {credentials.KEY_ENV: 'synthetic-memory-key'}, clear=True):
            self.assertTrue(credentials.load_api_key(self.path))
            self.assertEqual(os.environ[credentials.KEY_ENV], 'synthetic-memory-key')

    def test_public_permissions_and_symlinks_are_rejected(self):
        credentials.save_api_key('synthetic-key', self.path)
        self.path.chmod(0o644)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(credentials.CredentialError):
            credentials.load_api_key(self.path)
        self.path.chmod(0o600)
        link = self.path.with_name('link.env')
        link.symlink_to(self.path)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(credentials.CredentialError):
            credentials.load_api_key(link)

    def test_missing_file_and_invalid_key(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(credentials.load_api_key(self.path))
        for key in ('', 'bad\nkey', 'bad key', '\x00', 'x' * 4097):
            with self.assertRaises(credentials.CredentialError):
                credentials.save_api_key(key, self.path)
        self.assertFalse(self.path.exists())

    def test_only_supported_key_is_loaded_and_unrelated_settings_are_preserved(self):
        self.path.write_text('# private settings\nOTHER=value\nAIGATE_API_KEY=old-synthetic\n')
        self.path.chmod(0o600)
        credentials.save_api_key('new-synthetic', self.path)
        self.assertIn('OTHER=value', self.path.read_text())
        self.assertEqual(self.path.read_text().count('AIGATE_API_KEY='), 1)
        with patch.dict(os.environ, {}, clear=True):
            credentials.load_api_key(self.path)
            self.assertNotIn('OTHER', os.environ)

    def test_explain_automatically_loads_env_without_leaking_key(self):
        credentials.save_api_key('synthetic-auto-key', self.path)
        transport = FakeOpener()
        with patch.dict(os.environ, {}, clear=True), patch.object(credentials, 'DEFAULT_PATH', self.path):
            result = ai.explain(synthetic_payload(), consent=True, opener=transport)
        self.assertNotIn('synthetic-auto-key', str(result))
        self.assertNotIn('synthetic-auto-key', transport.calls[0].data.decode())
        self.assertEqual(transport.calls[0].get_header('Authorization'), 'Bearer synthetic-auto-key')


if __name__ == '__main__':
    unittest.main()
