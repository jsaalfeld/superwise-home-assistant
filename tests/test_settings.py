import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from superwise.models import controller_summary, live_summary
from superwise.settings import Settings, config


class SettingsTests(unittest.TestCase):
    def test_env_precedence_and_decimal_comma(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('SUPERWISE_SERIAL_NUMBER=100001\nSUPERWISE_RATED_POWER_KW="6,0"\n')
            with patch.dict(os.environ, {'SUPERWISE_SERIAL_NUMBER': '100002'}, clear=True):
                settings = Settings.from_mapping(config(path))
        self.assertEqual(settings.serial_number, '100002')
        self.assertEqual(settings.rated_power_kw, 6.0)

    def test_required_serial_and_optional_power(self):
        with self.assertRaises(ValueError):
            Settings.from_mapping({})
        settings = Settings.from_mapping({'SUPERWISE_SERIAL_NUMBER': '100001'})
        self.assertIsNone(settings.rated_power_kw)
        self.assertEqual(Settings.from_mapping({}, serial_override='100002').serial_number, '100002')
        for serial in ('abc123', '100001/view', '12345'):
            with self.subTest(serial=serial), self.assertRaises(ValueError):
                Settings.from_mapping({'SUPERWISE_SERIAL_NUMBER': serial})

    def test_invalid_power_rejected_and_credentials_not_in_repr(self):
        for power in ('0', '-5', 'NaN', 'inf', '6.0 kW', 'wrong'):
            with self.subTest(power=power), self.assertRaises(ValueError):
                Settings.from_mapping({'SUPERWISE_SERIAL_NUMBER': '100001',
                                       'SUPERWISE_RATED_POWER_KW': power})
        settings = Settings.from_mapping({'SUPERWISE_SERIAL_NUMBER': '100001',
                                          'SUPERWISE_PASSWORD': 'TEST_SECRET',
                                          'SUPERWISE_USERNAME': 'TEST_PRIVATE'})
        self.assertNotIn('TEST_SECRET', repr(settings))
        self.assertNotIn('TEST_PRIVATE', repr(settings))

    def test_estimate_requires_fresh_valid_percent_and_nameplate_power(self):
        with patch('superwise.models.time.time', return_value=1000):
            controller = {'lastActive': 999000, 'lpValue': 73.4}
            self.assertEqual(controller_summary(controller, 6.0)['estimated_power_kw'], 4.404)
            self.assertEqual(live_summary({'controlUnit': controller}, 6.0)
                             ['controller']['estimated_power_kw'], 4.404)
            self.assertIsNone(controller_summary(controller)['estimated_power_kw'])
            self.assertIsNone(controller_summary(dict(controller, lastActive=900000), 6.0)
                              ['estimated_power_kw'])
            for percent in ('NaN', None, -1, 101):
                with self.subTest(percent=percent):
                    self.assertIsNone(controller_summary(dict(controller, lpValue=percent), 6.0)
                                      ['estimated_power_kw'])
            self.assertEqual(controller_summary(dict(controller, lpValue=0), 6.0)
                             ['estimated_power_kw'], 0)
