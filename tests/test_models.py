import json
import time
import unittest
from unittest.mock import patch

import probe


class ProbeTests(unittest.TestCase):
    def test_page_json_is_parsed_without_executing_script(self):
        page = '<script>let controlUnit = {"name":"a;b", "nested":{"v":1}}; alert(1)</script>'
        self.assertEqual(probe.embedded(page, 'controlUnit')['name'], 'a;b')
        with self.assertRaises(ValueError):
            probe.embedded('<html>Login</html>', 'controlUnit')

    def test_live_payload_redacts_sensitive_controller_fields_and_nan(self):
        message = probe.live_summary({
            'controlUnit': {'pin': 'SECRET', 'owner': 'PRIVATE', 'usernames': ['PRIVATE'],
                            'lastActive': int(time.time() * 1000), 'value': 1.7e39,
                            'setpoint': 0, 'lpValue': 'NaN', 'processStatus': 'PS_FINISHED'},
            'sensors': [{'val': 'NaN', 'descr': {'identifier': 'LP0', 'unit': '%'}}],
        })
        encoded = json.dumps(message, allow_nan=False)
        self.assertNotIn('SECRET', encoded)
        self.assertNotIn('PRIVATE', encoded)
        self.assertTrue(message['controller']['fresh'])
        self.assertIsNone(message['controller']['value'])
        self.assertIsNone(message['sensors'][0]['value'])
        self.assertEqual(message['controller']['setpoint'], 0)

    def test_stale_cloud_state_is_not_fresh(self):
        with patch('superwise.models.time.time', return_value=1000):
            self.assertFalse(probe.controller_summary({'lastActive': 900000})['fresh'])
            self.assertFalse(probe.controller_summary({})['fresh'])
            self.assertFalse(probe.controller_summary({'lastActive': 1100000})['fresh'])

    def test_expired_session_does_not_trigger_login(self):
        client = probe.Client('https://www.superwise.eu', '/tmp/does-not-exist-probe-test')
        with patch.object(client, 'request', side_effect=probe.SessionExpired('expired')), \
                patch.object(client, 'login') as login:
            with self.assertRaises(probe.SessionExpired):
                client.snapshot()
            login.assert_not_called()


if __name__ == '__main__':
    unittest.main()
