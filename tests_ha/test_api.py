"""Protocol tests: no credentials, real device identifiers or live network."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.superwise.api import (
    AuthenticationError,
    CommandError,
    SuperwiseApi,
    SuperwiseError,
    validate_config,
)


@pytest.fixture
async def api():
    client = SuperwiseApi("https://www.superwise.eu", "100001", 6.0)
    yield client
    await client.close()


def response_context(status, location):
    response = MagicMock()
    response.status = status
    response.headers = {"Location": location}
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


async def test_redirect_to_login_does_not_reauthenticate(api):
    with patch.object(
        api.session, "request", return_value=response_context(302, "/login")
    ) as request:
        with pytest.raises(AuthenticationError):
            await api.request("/dashboard")
        assert request.call_count == 1


async def test_cross_origin_redirect_refused(api):
    with patch.object(
        api.session,
        "request",
        return_value=response_context(307, "https://other.invalid/login"),
    ) as request:
        with pytest.raises(SuperwiseError, match="Cross-origin"):
            await api.request(
                "/login", method="POST", data={"password": "synthetic"}, login=True
            )
        assert request.call_count == 1


async def test_persistent_cookies_survive_new_client(api):
    from yarl import URL

    api.session.cookie_jar.update_cookies({"SESSION": "synthetic"}, URL(api.base))
    saved = api.cookies()
    other = SuperwiseApi(api.base, "100001", cookies=saved)
    try:
        assert (
            other.session.cookie_jar.filter_cookies(URL(api.base))["SESSION"].value
            == "synthetic"
        )
    finally:
        await other.close()


async def test_state_redacts_pin_and_account_fields(api):
    api.request = AsyncMock(
        return_value=json.dumps(
            [{"serialNumber": "100001", "pin": "SECRET", "owner": "PRIVATE"}]
        )
    )
    result = await api.state()
    assert "SECRET" not in json.dumps(result)
    assert "PRIVATE" not in json.dumps(result)


async def test_stale_controller_cannot_start(api, snapshot):
    snapshot["controller"]["fresh"] = False
    api.state = AsyncMock(return_value=snapshot)
    api.request = AsyncMock()
    with pytest.raises(CommandError, match="stale"):
        await api.command("start")
    api.request.assert_not_called()


async def test_start_confirmed_by_new_timestamp_only_once(api, snapshot):
    after = deepcopy(snapshot)
    after["controller"].update(
        processStatus="PS_RUNNING", lastActive=snapshot["controller"]["lastActive"] + 1
    )
    api.state = AsyncMock(side_effect=[snapshot, snapshot, after])
    api.request = AsyncMock(return_value="")
    assert (await api.command("start"))["controller"]["processStatus"] == "PS_RUNNING"
    api.request.assert_awaited_once_with(
        "/controller/100001/start", method="POST", data={"delay_date": "0"}
    )


async def test_uncertain_start_not_repeated(api, snapshot):
    api.state = AsyncMock(return_value=snapshot)
    api.request = AsyncMock(side_effect=SuperwiseError("timeout"))
    with pytest.raises(CommandError, match="uncertain"):
        await api.command("start")
    assert api.request.await_count == 1


async def test_stop_requires_zero_outputs_and_setpoint(api, snapshot):
    before = deepcopy(snapshot)
    before["controller"]["processStatus"] = "PS_RUNNING"
    pending = deepcopy(snapshot)
    pending["controller"].update(
        lastActive=before["controller"]["lastActive"] + 1, doValue=1
    )
    after = deepcopy(pending)
    after["controller"]["doValue"] = 0
    api.state = AsyncMock(side_effect=[before, pending, after])
    api.request = AsyncMock(return_value="")
    with patch("custom_components.superwise.api.asyncio.sleep", new=AsyncMock()):
        result = await api.command("stop")
    assert result["controller"]["doValue"] == 0
    assert api.request.await_count == 1


async def test_program_write_verified_and_previous_returned(api, snapshot, program):
    changed = deepcopy(program)
    changed["segs"][0]["value"] = 199
    changed["pcrc"] = 456
    api.state = AsyncMock(return_value=snapshot)
    api.read_program = AsyncMock(side_effect=[deepcopy(program), changed])
    api.request = AsyncMock(return_value="true")
    result = await api.update_program(1, 1, {"value": 199})
    assert result["verified"]
    assert result["previous_program"]["segs"][0]["value"] == 200
    assert program["segs"][0]["value"] == 200
    assert api.request.await_count == 1
    sent = json.loads(api.request.call_args.kwargs["data"])
    assert sent["segs"][0]["value"] == 199


@pytest.mark.parametrize(
    "changes", [{"value": 5000}, {"rtime": 99}, {"dwell": 600}, {}]
)
async def test_invalid_program_edit_does_not_write(api, snapshot, program, changes):
    api.state = AsyncMock(return_value=snapshot)
    api.read_program = AsyncMock(return_value=deepcopy(program))
    api.request = AsyncMock()
    with pytest.raises(CommandError):
        await api.update_program(1, 1, changes)
    api.request.assert_not_called()


async def test_program_mismatch_not_silently_retried(api, snapshot, program):
    api.state = AsyncMock(return_value=snapshot)
    api.read_program = AsyncMock(return_value=deepcopy(program))
    api.request = AsyncMock(return_value="true")
    with pytest.raises(CommandError, match="differs"):
        await api.update_program(1, 1, {"value": 199})
    assert api.request.await_count == 1


async def test_sockjs_subscription_and_cleanup(api, snapshot):
    raw = {"controlUnit": {**snapshot["controller"], "pin": "SECRET"}, "sensors": []}
    frame = "MESSAGE\ndestination:/topic/100001/data\n\n" + json.dumps(raw) + "\x00"
    replies = iter(
        ["o", "", 'a["CONNECTED\\n\\n\\u0000"]', "", "a" + json.dumps([frame]), ""]
    )
    api.request = AsyncMock(side_effect=lambda *args, **kwargs: next(replies))
    stream = api.messages()
    value = await anext(stream)
    assert "SECRET" not in json.dumps(value)
    await stream.aclose()
    sent = [
        json.loads(call.kwargs["data"])[0]
        for call in api.request.call_args_list
        if call.args[0].endswith("xhr_send")
    ]
    assert any(f.startswith("SUBSCRIBE") for f in sent)
    assert sent[-1].startswith("DISCONNECT")


@pytest.mark.parametrize(
    "values",
    [
        {"serial_number": "12"},
        {"serial_number": "100001", "url": "http://example.invalid"},
        {"serial_number": "100001", "rated_power_kw": "nan"},
    ],
)
def test_invalid_settings(values):
    with pytest.raises(ValueError):
        validate_config(values)


async def test_program_readback_uses_program_topic(api, program):
    async def messages(topic, on_ready):
        assert topic == "prog"
        await on_ready()
        yield {"no": 2}
        yield program

    api.messages = messages
    api.request = AsyncMock(return_value="")
    assert (await api.read_program(1))["pcrc"] == 123
    api.request.assert_awaited_once_with("/program/100001/request/1")


async def test_non_minute_dwell_rejected(api, snapshot, program):
    program["segDef"]["tRes"] = "TIME_RES_SEC"
    api.state = AsyncMock(return_value=snapshot)
    api.read_program = AsyncMock(return_value=program)
    api.request = AsyncMock()
    with pytest.raises(CommandError, match="minute-resolution"):
        await api.update_program(1, 1, {"dwell": 2})
    api.request.assert_not_called()


async def test_auth_failure_during_command_preserved(api, snapshot):
    api.state = AsyncMock(return_value=snapshot)
    api.request = AsyncMock(side_effect=AuthenticationError("expired"))
    with pytest.raises(AuthenticationError):
        await api.command("start")
    assert api.request.await_count == 1


async def test_offline_stop_is_attempted_once(api, snapshot):
    before = deepcopy(snapshot)
    before["controller"]["fresh"] = False
    after = deepcopy(snapshot)
    after["controller"]["lastActive"] += 1
    after["controller"]["processStatus"] = "PS_STOPPED"
    api.state = AsyncMock(side_effect=[before, after])
    api.request = AsyncMock(return_value="")
    assert (await api.command("stop"))["controller"]["setpoint"] == 0
    api.request.assert_awaited_once_with(
        "/controller/100001/stop", method="GET", data=None
    )


async def test_login_http_redirect_is_upgraded_without_credentials(api):
    first = response_context(302, "http://www.superwise.eu/dashboard")
    response = MagicMock()
    response.status = 200
    response.url = "https://www.superwise.eu/dashboard"
    response.text = AsyncMock(return_value="Dashboard")
    second = MagicMock()
    second.__aenter__ = AsyncMock(return_value=response)
    second.__aexit__ = AsyncMock(return_value=False)
    with patch.object(api.session, "request", side_effect=[first, second]) as request:
        assert (
            await api.request(
                "/login", method="POST", data={"password": "synthetic"}, login=True
            )
            == "Dashboard"
        )
    calls = request.call_args_list
    assert calls[1].args[0] == "GET"
    assert calls[1].args[1] == "https://www.superwise.eu/dashboard"
    assert calls[1].kwargs["data"] is None
    assert all(call.args[1].startswith("https://") for call in calls)


@pytest.mark.parametrize(
    "target",
    [
        "http://www.superwise.eu:8080/dashboard",
        "https://synthetic@www.superwise.eu/dashboard",
        "http://other.invalid/dashboard",
    ],
)
async def test_redirect_cannot_change_host_port_or_userinfo(api, target):
    with (
        patch.object(
            api.session, "request", return_value=response_context(302, target)
        ) as request,
        pytest.raises(SuperwiseError, match="Cross-origin"),
    ):
        await api.request(
            "/login", method="POST", data={"password": "synthetic"}, login=True
        )
    assert request.call_count == 1


async def test_json_discovery_and_state_select_only_configured_controller(
    api, snapshot
):
    first = {
        **snapshot["controller"],
        "pin": "PRIVATE_PIN",
        "usernames": ["PRIVATE_USER"],
    }
    second = {**snapshot["controller"], "serialNumber": "100002", "value": 999}
    api.request = AsyncMock(return_value=json.dumps([second, first]))
    controllers = await api.controllers()
    assert set(controllers) == {"100001", "100002"}
    assert "PRIVATE" not in json.dumps(controllers)
    state = await api.state()
    assert state["controller"]["value"] == 21.5
    assert state["controller"]["error"] == 0
    assert state["controller"]["fresh"]
    assert all(
        call.args == ("/controller/menu",) for call in api.request.call_args_list
    )


@pytest.mark.parametrize(
    "response",
    [
        "<html>Login</html>",
        "null",
        "{}",
        "[null]",
        '[{"serialNumber": "100001/view"}]',
        '[{"serialNumber": "100001"}, {"serialNumber": "100001"}]',
        '[{"serialNumber": "100001", "lastActive": "invalid"}]',
    ],
)
async def test_invalid_discovery_responses_rejected_without_raw_data(api, response):
    api.request = AsyncMock(return_value=response)
    with pytest.raises(SuperwiseError, match="Unexpected controller response"):
        await api.controllers()


async def test_missing_configured_controller_not_replaced_by_another(api):
    api.request = AsyncMock(return_value='[{"serialNumber": "100002"}]')
    with pytest.raises(SuperwiseError, match="not found"):
        await api.state()


async def test_json_status_retains_stale_state_and_missing_measurements(api):
    api.request = AsyncMock(
        return_value=json.dumps(
            [{"serialNumber": "100001", "lastActive": 1, "pin": "PRIVATE"}]
        )
    )
    state = await api.state()
    assert not state["controller"]["fresh"]
    assert state["controller"]["lpValue"] is None
    assert state["controller"]["estimated_power_kw"] is None


async def test_login_page_with_http_200_is_not_accepted(api):
    response = MagicMock(status=200, url="https://www.superwise.eu/login")
    response.text = AsyncMock(
        return_value='<html><button id="login-button">Sign in</button></html>'
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    with (
        patch.object(api.session, "request", return_value=context),
        pytest.raises(AuthenticationError),
    ):
        await api.request("/controller/menu")
