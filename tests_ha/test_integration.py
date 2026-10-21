"""Exercise actual Home Assistant config flows, entities and unload."""

import time
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
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
            data={
                k: v
                for k, v in DATA.items()
                if k not in ("session_cookies", "serial_number")
            },
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


@pytest.mark.parametrize("uptime", [30, 1000])
async def test_setup_entities_and_unload_reuse_session(hass, mock_api, uptime):
    with patch("custom_components.superwise.coordinator.time", wraps=time) as clock:
        clock.monotonic.return_value = uptime
        entry = await setup(hass, mock_api)
    mock_api.login.assert_not_called()
    mock_api.programs.assert_awaited_once()
    mock_api.firings.assert_awaited_once()
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


async def test_rejected_stored_password_requests_reauth(hass, mock_api):
    entry = await setup(hass, mock_api)
    mock_api.state.side_effect = AuthenticationError("expired")
    mock_api.login.side_effect = AuthenticationError("rejected")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.authentication_lost
    assert any(
        f["context"].get("source") == "reauth"
        for f in hass.config_entries.flow.async_progress()
    )
    mock_api.login.assert_awaited_once_with(DATA["username"], DATA["password"])
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "submission", [{}, {"password": ""}, {"password": "new-synthetic"}]
)
async def test_reauth_requires_submission(hass, mock_api, submission):
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
        assert "synthetic" not in repr(result["data_schema"])
        mock_api.login.assert_not_called()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], submission
        )
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        expected_password = submission.get("password") or DATA["password"]
        mock_api.login.assert_awaited_once_with(DATA["username"], expected_password)
        assert entry.data["password"] == expected_password


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


async def test_expired_session_renews_and_persists_without_reload(hass, mock_api):
    entry = await setup(hass, mock_api)
    snapshot = deepcopy(mock_api.state.return_value)
    mock_api.state.side_effect = [AuthenticationError("expired"), snapshot]
    mock_api.cookies = lambda: [{"name": "SESSION", "value": "renewed", "path": "/"}]
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as reload:
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        reload.assert_not_called()
    assert not entry.runtime_data.authentication_lost
    mock_api.login.assert_awaited_once_with(DATA["username"], DATA["password"])
    assert entry.data["session_cookies"][0]["value"] == "renewed"
    mock_api.state.side_effect = AuthenticationError("expired again")
    await entry.runtime_data.async_refresh()
    assert mock_api.login.await_count == 1
    assert not entry.runtime_data.authentication_lost
    await hass.config_entries.async_unload(entry.entry_id)


async def test_expired_command_is_not_replayed(hass, mock_api):
    entry = await setup(hass, mock_api, {"enable_control": True})
    snapshot = deepcopy(mock_api.state.return_value)
    mock_api.command.side_effect = AuthenticationError("expired")
    mock_api.state.side_effect = [AuthenticationError("expired"), snapshot]
    with pytest.raises(HomeAssistantError, match="check controller state"):
        await entry.runtime_data.operation("start")
    mock_api.command.assert_awaited_once_with("start")
    mock_api.login.assert_awaited_once()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_discovery_selects_controller_without_second_login(hass, mock_api):
    mock_api.controllers.return_value = {
        "100001": {"name": "Test kiln", "serialNumber": "100001"},
        "100002": {"name": "Other kiln", "serialNumber": "100002"},
    }
    credentials = {
        k: DATA[k] for k in ("url", "username", "password", "rated_power_kw")
    }
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
            "superwise", context={"source": SOURCE_USER}, data=credentials
        )
        assert result["step_id"] == "controller"
        with pytest.raises(InvalidData):
            await hass.config_entries.flow.async_configure(
                result["flow_id"], {"serial_number": "999999"}
            )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"serial_number": "100002"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["serial_number"] == "100002"
    assert result["result"].unique_id == "https://www.superwise.eu:100002"
    assert result["title"] == "Other kiln"
    mock_api.login.assert_awaited_once()
    mock_api.controllers.assert_awaited_once()
    mock_api.command.assert_not_called()


async def test_discovery_without_controllers_aborts(hass, mock_api):
    mock_api.controllers.return_value = {}
    with patch(
        "custom_components.superwise.config_flow.SuperwiseApi", return_value=mock_api
    ):
        result = await hass.config_entries.flow.async_init(
            "superwise",
            context={"source": SOURCE_USER},
            data={k: DATA[k] for k in ("url", "username", "password")},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_controllers"
    mock_api.close.assert_awaited_once()


async def test_existing_controller_via_another_account_is_not_duplicated(
    hass, mock_api
):
    MockConfigEntry(
        domain="superwise", data=DATA, unique_id="https://www.superwise.eu:100001"
    ).add_to_hass(hass)
    with patch(
        "custom_components.superwise.config_flow.SuperwiseApi", return_value=mock_api
    ):
        result = await hass.config_entries.flow.async_init(
            "superwise",
            context={"source": SOURCE_USER},
            data={**DATA, "username": "another-account"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize("initial_error", [0, None])
async def test_error_sensor_preserves_zero_and_updates(hass, mock_api, initial_error):
    from homeassistant.helpers import entity_registry as er

    mock_api.state.return_value["controller"]["error"] = initial_error
    entry = await setup(hass, mock_api)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "superwise", f"{entry.unique_id}_error"
    )
    assert hass.states.get(entity_id).state == "0"
    updated = deepcopy(entry.runtime_data.data)
    updated["controller"]["error"] = 42
    entry.runtime_data.async_set_updated_data(updated)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "42"
    updated = deepcopy(updated)
    updated["controller"].pop("error")
    entry.runtime_data.async_set_updated_data(updated)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "unavailable"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_discovery_rejected_credentials_do_not_create_entry(hass, mock_api):
    mock_api.login.side_effect = AuthenticationError("Synthetic rejected password")
    with patch(
        "custom_components.superwise.config_flow.SuperwiseApi", return_value=mock_api
    ):
        result = await hass.config_entries.flow.async_init(
            "superwise",
            context={"source": SOURCE_USER},
            data={k: DATA[k] for k in ("url", "username", "password")},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    mock_api.controllers.assert_not_called()
    mock_api.close.assert_awaited_once()
    assert "synthetic" not in repr(result["data_schema"])
