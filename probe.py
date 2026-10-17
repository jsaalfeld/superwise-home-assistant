#!/usr/bin/env python3
"""Compatibility entry point for the read-only Superwise research probe."""
from superwise.client import Client, SessionExpired
from superwise.models import (
    embedded, pick, number, controller_summary, sensor_summary, live_summary,
)
from superwise.cli import config, main, run


if __name__ == '__main__':
    raise SystemExit(run())
