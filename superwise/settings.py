"""Environment settings for the standalone diagnostic client."""
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import re


def config(path='.env'):
    result = {}
    source = Path(path)
    if source.exists():
        for line in source.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                result[key.strip()] = value.strip().strip('\"\'')
    result.update({k: v for k, v in os.environ.items() if k.startswith('SUPERWISE_')})
    return result


@dataclass(frozen=True)
class Settings:
    url: str
    serial_number: str
    rated_power_kw: float | None
    username: str = field(default='', repr=False)
    password: str = field(default='', repr=False)

    @classmethod
    def from_mapping(cls, values, serial_override=None):
        serial = str(serial_override if serial_override is not None else
                     values.get('SUPERWISE_SERIAL_NUMBER', '')).strip()
        if not re.fullmatch(r'[0-9]{6}', serial):
            raise ValueError('Set SUPERWISE_SERIAL_NUMBER to the six-digit controller serial')
        power = str(values.get('SUPERWISE_RATED_POWER_KW', '')).strip()
        rated = None
        if power:
            try:
                rated = float(power.replace(',', '.'))
            except ValueError:
                raise ValueError('SUPERWISE_RATED_POWER_KW must be a positive number in kW') from None
            if not math.isfinite(rated) or rated <= 0:
                raise ValueError('SUPERWISE_RATED_POWER_KW must be a positive number in kW')
        return cls(values.get('SUPERWISE_URL', 'https://www.superwise.eu'), serial,
                   rated, values.get('SUPERWISE_USERNAME', ''),
                   values.get('SUPERWISE_PASSWORD', ''))
