import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from case_controls import CaseControls


class CaseControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        for sid in ('PPMI_41282', 'PPMI_41293'):
            path = root/'cases'/sid/'config.json'
            path.parent.mkdir(parents=True)
            path.write_text('{}')
        self.action = Mock(return_value={'ok': True})
        self.controls = CaseControls(self.action, root)
        self.controls.send = Mock()

    def tearDown(self):
        self.controls.close()
        self.tmp.cleanup()

    def request(self, sid, request_id, **extra):
        msg = dict(type='action', id=request_id, action='report',
                   config=f'cases/{sid}/config.json', reference='config', consent=False)
        msg.update(extra)
        self.controls.receive(self.controls, msg, [])

    def test_repeated_case_switch_uses_request_not_stale_trait(self):
        self.controls.config = 'stale.json'
        for i, sid in enumerate(('PPMI_41282', 'PPMI_41293', 'PPMI_41282')):
            self.request(sid, str(i))
            self.action.assert_called_with(f'cases/{sid}/config.json', 'config', False, 'report')
            self.assertEqual(self.controls.send.call_args.args[0]['type'], 'done')
        self.assertEqual(self.action.call_count, 3)
        self.assertEqual(len(self.controls.cases), 2)

    def test_no_duplicate_execution(self):
        self.request('PPMI_41282', 'same')
        self.request('PPMI_41293', 'same')
        self.assertEqual(self.action.call_count, 1)

    def test_ping_never_runs_analysis(self):
        self.controls.receive(self.controls, dict(type='ping', id='hello'), [])
        self.controls.send.assert_called_once_with(dict(type='ready', id='hello'))
        self.action.assert_not_called()

    def test_consent_and_errors(self):
        self.request('PPMI_41282', 'process', action='process')
        self.action.assert_not_called()
        self.assertFalse(self.controls.send.call_args.args[0]['ok'])
        self.action.side_effect = ValueError('failed load')
        self.request('PPMI_41282', 'error')
        self.assertIn('failed load', self.controls.send.call_args.args[0]['error'])

    def test_closed_interface_ignores_requests(self):
        self.controls.close()
        self.request('PPMI_41282', 'closed')
        self.action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
