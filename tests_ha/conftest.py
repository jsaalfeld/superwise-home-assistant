"""Home Assistant tests with synthetic controller data only."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def snapshot():
    return {
        "controller": {
            "serialNumber": "100001",
            "name": "Test kiln",
            "type": "TC75",
            "lastActive": int(time.time() * 1000),
            "fresh": True,
            "processStatus": "PS_IDLE",
            "progNumber": 1,
            "segNumber": 255,
            "segmentMode": "SKP_DN",
            "remainingSegmentSeconds": 0,
            "value": 21.5,
            "setpoint": 0.0,
            "lpValue": None,
            "doValue": 0,
            "error": 0,
            "rated_power_kw": 6.0,
            "estimated_power_kw": None,
        }
    }


@pytest.fixture
def program():
    return {
        "no": 1,
        "name": "Test program",
        "pcrc": 123,
        "segDef": {"vMin": 20, "vMax": 1300, "dMax": 600, "tRes": "TIME_RES_MIN"},
        "segs": [{"rtime": 20, "value": 200, "dwell": 10}],
    }


@pytest.fixture
def mock_api(snapshot, program):
    api = AsyncMock()
    api.power = 6.0
    api.state.return_value = snapshot
    api.controllers.return_value = {"100001": snapshot["controller"]}
    api.programs.return_value = {1: program}
    api.firings.return_value = [
        {
            "id": "test-record",
            "startAt": 100000,
            "endAt": 160000,
            "status": "PS_FINISHED",
        }
    ]
    api.cookies = lambda: [{"name": "SESSION", "value": "synthetic", "path": "/"}]

    async def messages(*args, **kwargs):
        await asyncio.Event().wait()
        yield {}

    api.messages = messages
    return api
