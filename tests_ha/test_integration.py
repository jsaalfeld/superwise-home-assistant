"""Exercise actual Home Assistant config flows, entities and unload."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from custom_components.superwise.api import AuthenticationError

DATA = {
    "url": "https://www.superwise.eu",
    "serial_number": "100001",
    "username": "test-account",
    "password": "synthetic",
    "rated_power_kw": 6.0,
    "session_cookies": [{"name": "SESSION", "value": "synthetic", "path": "/"}],
}


async def test_user_flow_creates_session_once(hass, mock_api):
    with (
        patch(
            "custom_components.superwise.config_flow.SuperwiseApi",
            return_value=mock_api,
        ),
        patch(
            "custom_components.superwise.async_setup_entry", return_value=True
        ) as setup_entry,
    ):
        result = await hass.config_entries.flow.async_init(
            "superwise",
            context={"source": SOURCE_USER},
            data={k: v for k, v in DATA.items() if k != "session_cookies"},
        )
        # Flow completion schedules entry setup in the background.
        await hass.async_block_till_done()
    setup_entry.assert_awaited_once()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["session_cookies"]
    mock_api.login.assert_awaited_once_with("test-account", "synthetic")
    mock_api.close.assert_awaited_once()


async def test_duplicate_aborts_before_displacing_session(hass, mock_api):
    entry = MockConfigEntry(
        domain="superwise", data=DATA, unique_id="https://www.superwise.eu:100001"
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.superwise.config_flow.SuperwiseApi", return_value=mock_api
    ):
        result = await hass.config_entries.flow.async_init(
            "superwise", context={"source": SOURCE_USER}, data=DATA
        )
    assert result["type"] is FlowResultType.ABORT
    mock_api.login.assert_not_called()


async def setup(hass, api, options=None):
    entry = MockConfigEntry(
        domain="superwise",
        data=DATA,
        unique_id="https://www.superwise.eu:100001",
        options=options or {},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.superwise.SuperwiseApi", return_value=api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_setup_entities_and_unload_reuse_session(hass, mock_api):
    entry = await setup(hass, mock_api)
    mock_api.login.assert_not_called()
    states = hass.states.async_all()
    assert any(s.state == "21.5" and s.domain == "sensor" for s in states)
    assert any(s.state == "Test program" for s in states)
    assert len([s for s in states if s.domain == "button"]) == 4
    assert any(s.domain == "select" and s.state == "unavailable" for s in states)
    assert hass.services.has_service("superwise", "read_program")
    assert await hass.config_entries.async_unload(entry.entry_id)
    mock_api.close.assert_awaited_once()


async def test_control_disabled_does_not_call_api(hass, mock_api):
    entry = await setup(hass, mock_api)
    with pytest.raises(HomeAssistantError, match="Enable remote control"):
        await entry.runtime_data.operation("start")
    mock_api.command.assert_not_called()
    mock_api.command.return_value = deepcopy(mock_api.state.return_value)
    await entry.runtime_data.operation("stop")
    mock_api.command.assert_awaited_once_with("stop")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_control_enabled_calls_and_updates(hass, mock_api):
    entry = await setup(hass, mock_api, {"enable_control": True})
    mock_api.command.return_value = deepcopy(mock_api.state.return_value)
    mock_api.command.return_value["controller"]["processStatus"] = "PS_RUNNING"
    await entry.runtime_data.operation("start")
    assert entry.runtime_data.data["controller"]["processStatus"] == "PS_RUNNING"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_stale_measurements_become_unavailable(hass, mock_api):
    entry = await setup(hass, mock_api)
    entry.runtime_data.data["controller"]["lastActive"] = 1
    await entry.runtime_data._tick(dt_util.utcnow())
    assert entry.runtime_data.data["controller"]["fresh"] is False
    await hass.async_block_till_done()
    assert all(s.state == "unavailable" for s in hass.states.async_all("sensor"))
    await hass.config_entries.async_unload(entry.entry_id)


async def test_auth_failure_requests_reauth_not_login(hass, mock_api):
    entry = await setup(hass, mock_api)
    mock_api.state.side_effect = AuthenticationError("expired")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.authentication_lost
    assert any(
        f["context"].get("source") == "reauth"
        for f in hass.config_entries.flow.async_progress()
    )
    mock_api.login.assert_not_called()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reauth_requires_submission(hass, mock_api):
    entry = MockConfigEntry(
        domain="superwise", data=DATA, unique_id="https://www.superwise.eu:100001"
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.superwise.config_flow.SuperwiseApi",
            return_value=mock_api,
        ),
        patch(
            "custom_components.superwise.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            "superwise",
            context={"source": "reauth", "entry_id": entry.entry_id},
            data=DATA,
        )
        assert result["step_id"] == "reauth_confirm"
        mock_api.login.assert_not_called()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "new-synthetic"}
        )
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        mock_api.login.assert_awaited_once()


async def test_options_validate_without_cloud_login(hass, mock_api):
    entry = MockConfigEntry(
        domain="superwise", data=DATA, unique_id="https://www.superwise.eu:100001"
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"rated_power_kw": -1, "enable_control": True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_power"


async def test_program_and_history_actions_return_responses(hass, mock_api):
    entry = await setup(hass, mock_api, {"enable_control": True})
    mock_api.read_program.return_value = {"no": 1, "name": "Test program"}
    mock_api.update_program.return_value = {
        "verified": True,
        "previous_program": {"no": 1},
    }
    mock_api.history.return_value = {"firing": {"id": "test-record"}, "curves": {}}
    response = await hass.services.async_call(
        "superwise",
        "read_program",
        {"config_entry_id": entry.entry_id, "program": 1},
        blocking=True,
        return_response=True,
    )
    assert response["program"]["no"] == 1
    response = await hass.services.async_call(
        "superwise",
        "update_program",
        {
            "config_entry_id": entry.entry_id,
            "program": 1,
            "segment": 1,
            "temperature": 199,
        },
        blocking=True,
        return_response=True,
    )
    assert response["verified"]
    mock_api.update_program.assert_awaited_once_with(
        number=1, segment=1, changes={"value": 199}
    )
    response = await hass.services.async_call(
        "superwise",
        "list_firings",
        {"config_entry_id": entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert response["firings"][0]["id"] == "test-record"
    response = await hass.services.async_call(
        "superwise",
        "get_firing_history",
        {"config_entry_id": entry.entry_id, "firing_id": "test-record"},
        blocking=True,
        return_response=True,
    )
    assert response["firing"]["id"] == "test-record"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_service_descriptions_load(hass, mock_api):
    from homeassistant.helpers.service import async_get_all_descriptions

    entry = await setup(hass, mock_api)
    descriptions = await async_get_all_descriptions(hass)
    assert descriptions["superwise"]["update_program"]["fields"]["segment"]["required"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_program_edit_is_locked_in_monitoring_mode(hass, mock_api):
    entry = await setup(hass, mock_api)
    with pytest.raises(HomeAssistantError, match="Enable remote control"):
        await hass.services.async_call(
            "superwise",
            "update_program",
            {
                "config_entry_id": entry.entry_id,
                "program": 1,
                "segment": 1,
                "temperature": 199,
            },
            blocking=True,
            return_response=True,
        )
    mock_api.update_program.assert_not_called()
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("value, expected", [(1, 1), (1.0, 1), ("2", 2), (0.0, 0)])
def test_service_whole_numbers_accept_selector_values(value, expected):
    from custom_components.superwise.services import whole_number

    assert whole_number(value) == expected


@pytest.mark.parametrize("value", [True, 1.5, -1.0, float("nan"), float("inf"), "1.5"])
def test_service_fractional_numbers_are_not_truncated(value):
    import voluptuous as vol

    from custom_components.superwise.services import whole_number

    with pytest.raises(vol.Invalid):
        whole_number(value)
