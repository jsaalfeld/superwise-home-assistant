"""Protocol-shaped synthetic data; no account, cookies or network required."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from superwise.client import Client
from superwise.cli import main


def page(**variables):
    return '<script>' + '\n'.join(
        f'let {name} = {json.dumps(value)};' for name, value in variables.items()) + '</script>'


class ClientTests(unittest.TestCase):
    def test_snapshot_joins_program_and_firing_data_without_controller_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Client('superwise.eu', Path(directory) / 'cookies')
            pages = {
                '/dashboard': page(controllers={'content': [{'serialNumber': '100001'}]}),
                '/controller/100001/view': page(
                    controlUnit={'serialNumber': '100001', 'progNumber': 2,
                                 'pin': 'TEST_SECRET', 'usernames': ['TEST_PRIVATE']},
                    sensors=[{'identifier': 'IN0', 'unit': '°C'}], alarms=[], prcsAlarms=[]),
                '/program/100001': page(programs=[{
                    'number': 2, 'payload': json.dumps({'no': 2, 'name': 'Testprogramm', 'segs': []})}]),
                '/firings': page(firings=[
                    {'id': 'test-firing', 'serialNumber': '100001', 'startAt': 1000, 'endAt': 2000},
                    {'id': 'other-controller', 'serialNumber': '100002'}]),
                '/controller/100001/onlinestatus': 'Offline',
            }
            with patch.object(client, 'request', side_effect=lambda path: pages[path]) as request:
                result = client.snapshot()
            self.assertEqual(client.base, 'https://www.superwise.eu')
            self.assertEqual(result['programs'][0]['definition']['name'], 'Testprogramm')
            self.assertEqual([f['id'] for f in result['firings']], ['test-firing'])
            self.assertEqual(result['online_status'], 'Offline')
            self.assertFalse(result['controller']['fresh'])
            self.assertNotIn('TEST_SECRET', json.dumps(result))
            self.assertNotIn('TEST_PRIVATE', json.dumps(result))
            self.assertEqual(request.call_count, 5)

    def test_login_redirect_is_reported_as_expired_without_post(self):
        from superwise.client import SessionExpired

        class Response:
            url = 'https://www.superwise.eu/login'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'<html>Login</html>'

        with tempfile.TemporaryDirectory() as directory:
            client = Client('superwise.eu', Path(directory) / 'cookies')
            with patch.object(client.opener, 'open', return_value=Response()) as opened:
                with self.assertRaises(SessionExpired):
                    client.request('/dashboard')
            self.assertEqual(opened.call_count, 1)
            self.assertEqual(opened.call_args.args[0].get_method(), 'GET')

    def test_help_does_not_open_a_client_or_read_credentials(self):
        with patch('sys.argv', ['superwise', '--help']), \
                patch('superwise.cli.Client') as client, \
                patch('superwise.cli.config') as config, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                main()
        self.assertEqual(result.exception.code, 0)
        client.assert_not_called()
        config.assert_not_called()
