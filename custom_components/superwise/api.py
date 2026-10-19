"""Asynchronous client for the observed SuperWise web protocol."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from copy import deepcopy
from http.cookies import SimpleCookie
from urllib.parse import urljoin, urlsplit

import aiohttp
from yarl import URL

from .const import DEFAULT_URL, IDLE
from .models import controller_summary, embedded, live_summary


class SuperwiseError(Exception):
    """Communication or protocol failure; messages never contain raw responses."""


class AuthenticationError(SuperwiseError):
    """The account session is unavailable."""


class CommandError(SuperwiseError):
    """A command was rejected or its result could not be verified."""


def validate_config(values):
    """Normalize UI input without including secrets in exceptions."""
    result = dict(values)
    base = str(values.get("url", DEFAULT_URL)).strip().rstrip("/")
    if base in ("superwise.eu", "www.superwise.eu", "https://superwise.eu"):
        base = DEFAULT_URL
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid_url")
    serial = str(values.get("serial_number", "")).strip()
    if not re.fullmatch(r"[0-9]{6}", serial):
        raise ValueError("invalid_serial")
    power = str(values.get("rated_power_kw", "")).strip()
    try:
        power = float(power.replace(",", ".")) if power else 0.0
    except ValueError:
        raise ValueError("invalid_power") from None
    if not math.isfinite(power) or power < 0:
        raise ValueError("invalid_power")
    result.update(url=base, serial_number=serial, rated_power_kw=power)
    return result


class SuperwiseApi:
    """One isolated session per configured account; never auto-login."""

    def __init__(self, base, serial, power=None, cookies=None, session=None):
        self.base = base
        self.serial = serial
        self.power = power or None
        self.session = session or aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=25), cookie_jar=aiohttp.CookieJar()
        )
        self._owns_session = session is None
        for saved in cookies or []:
            cookie = SimpleCookie()
            cookie[saved["name"]] = saved["value"]
            for key in ("domain", "path", "secure", "expires", "max-age"):
                if saved.get(key):
                    cookie[saved["name"]][key] = saved[key]
            self.session.cookie_jar.update_cookies(cookie, response_url=URL(base))

    def cookies(self):
        """Private session data for HA config storage, never diagnostics."""
        return [
            dict(
                name=c.key,
                value=c.value,
                **{k: c[k] for k in ("domain", "path", "secure", "expires", "max-age")},
            )
            for c in self.session.cookie_jar
        ]

    async def close(self):
        if self._owns_session:
            await self.session.close()

    async def request(
        self,
        path,
        *,
        method="GET",
        data=None,
        content_type=None,
        login=False,
        timeout=20,
    ):
        """Follow only same-origin redirects and detect displaced sessions."""
        url = self.base + path
        headers = {"User-Agent": "Superwise-HomeAssistant/0.2"}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            async with asyncio.timeout(timeout):
                for _ in range(5):
                    async with self.session.request(
                        method, url, data=data, headers=headers, allow_redirects=False
                    ) as response:
                        if response.status in (401, 403):
                            raise AuthenticationError("Session unavailable")
                        if response.status in (301, 302, 303, 307, 308):
                            target_url = URL(
                                urljoin(url, response.headers.get("Location", ""))
                            )
                            origin = URL(self.base).origin()
                            # The cloud emits an absolute http:// redirect after login.
                            # Upgrade it locally; never send cookies or credentials over HTTP.
                            if (
                                target_url.scheme == "http"
                                and target_url.host == origin.host
                                and target_url.port == 80
                            ):
                                target_url = target_url.with_scheme("https").with_port(
                                    None if origin.port == 443 else origin.port
                                )
                            if (
                                target_url.user
                                or target_url.password
                                or (target_url.scheme, target_url.host, target_url.port)
                                != (origin.scheme, origin.host, origin.port)
                            ):
                                raise SuperwiseError("Cross-origin redirect refused")
                            target = str(target_url)
                            if urlsplit(target).path == "/login" and not login:
                                raise AuthenticationError("Session expired or replaced")
                            if response.status in (301, 302, 303):
                                method, data = "GET", None
                            url = target
                            continue
                        if response.status >= 400:
                            raise SuperwiseError(
                                f"Server returned HTTP {response.status}"
                            )
                        text = await response.text()
                        if not login and (
                            urlsplit(str(response.url)).path == "/login"
                            or 'id="login-button"' in text
                        ):
                            raise AuthenticationError("Session expired or replaced")
                        return text
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SuperwiseError("Cloud connection failed") from err
        raise SuperwiseError("Too many redirects")

    async def login(self, username, password):
        await self.request("/login", login=True)
        await self.request(
            "/login",
            method="POST",
            data={"username": username, "password": password},
            login=True,
        )
        await self.request("/dashboard")

    async def state(self):
        try:
            page = await self.request(f"/controller/{self.serial}/view")
            raw = embedded(page, "controlUnit")
            if str(raw["serialNumber"]) != self.serial:
                raise SuperwiseError("Controller mismatch")
            return {"controller": controller_summary(raw, self.power)}
        except (ValueError, KeyError, TypeError) as err:
            raise SuperwiseError("Unexpected controller response") from err

    async def programs(self):
        try:
            page = await self.request(f"/program/{self.serial}")
            return {
                int(p["number"]): json.loads(p["payload"])
                for p in embedded(page, "programs")
            }
        except (ValueError, KeyError, TypeError) as err:
            raise SuperwiseError("Unexpected program response") from err

    async def firings(self):
        try:
            page = await self.request("/firings")
            return [
                {
                    k: f.get(k)
                    for k in (
                        "id",
                        "status",
                        "programNumber",
                        "startAt",
                        "endAt",
                        "recording",
                    )
                }
                for f in embedded(page, "firings")
                if str(f["serialNumber"]) == self.serial
            ]
        except (ValueError, KeyError, TypeError) as err:
            raise SuperwiseError("Unexpected firing response") from err

    async def messages(self, topic="data", on_ready=None):
        """Bounded XHR requests; reconnect is handled without logging in."""
        endpoint = "/ws/000/" + uuid.uuid4().hex

        async def send(frame):
            await self.request(
                endpoint + "/xhr_send",
                method="POST",
                data=json.dumps([frame]),
                content_type="application/json",
            )

        async def receive():
            text = (
                await self.request(
                    endpoint + "/xhr",
                    method="POST",
                    data=b"",
                    content_type="application/json",
                    timeout=35,
                )
            ).strip()
            if text.startswith("c"):
                raise SuperwiseError("Live connection closed")
            try:
                return json.loads(text[1:]) if text.startswith("a") else []
            except ValueError as err:
                raise SuperwiseError("Invalid live envelope") from err

        await receive()
        await send("CONNECT\naccept-version:1.1,1.0\nheart-beat:0,0\n\n\x00")
        try:
            while True:
                for frame in await receive():
                    if frame.startswith("CONNECTED"):
                        await send(
                            f"SUBSCRIBE\nid:ha\ndestination:/topic/{self.serial}/{topic}\n\n\x00"
                        )
                        if on_ready:
                            await on_ready()
                    elif frame.startswith("MESSAGE"):
                        try:
                            payload = json.loads(
                                frame.split("\n\n", 1)[1].rstrip("\x00")
                            )
                            if topic == "data":
                                yield live_summary(payload, self.power)
                            else:
                                yield payload
                        except (ValueError, KeyError, TypeError, IndexError) as err:
                            raise SuperwiseError("Invalid live payload") from err
                    elif frame.startswith("ERROR"):
                        raise SuperwiseError("Subscription rejected")
        finally:
            # Unload/cancellation must not leave a second login or a pending write.
            try:
                await send("DISCONNECT\n\n\x00")
            except (SuperwiseError, asyncio.CancelledError):
                pass

    async def read_program(self, number):
        """Request and verify the controller definition, not just the cloud cache."""

        async def request():
            await self.request(f"/program/{self.serial}/request/{number}")

        stream = self.messages("prog", on_ready=request)
        try:
            async with asyncio.timeout(30):
                async for payload in stream:
                    if payload.get("no") == number:
                        return payload
        except TimeoutError as err:
            raise CommandError(
                "Program readback timed out; no write was repeated"
            ) from err
        finally:
            await stream.aclose()
        raise CommandError("No program readback received")

    async def ensure_idle(self):
        state = (await self.state())["controller"]
        if (
            not state["fresh"]
            or state["processStatus"] not in IDLE
            or (state.get("doValue") != 0 or state.get("setpoint") != 0)
        ):
            raise CommandError("A fresh idle controller with outputs off is required")
        return state

    async def command(self, action, program=None):
        """Issue once and verify new controller feedback. Never retry a start."""
        before = (await self.state())["controller"]
        if not before["fresh"] and action != "stop":
            raise CommandError("Controller data is stale")
        if action in ("select", "start"):
            await self.ensure_idle()
        if action == "pause" and before["processStatus"] != "PS_RUNNING":
            raise CommandError("Only running programs can be paused")
        if action == "continue" and before["processStatus"] != "PS_HOLDED":
            raise CommandError("Only paused programs can be continued")
        if action == "select":
            if program not in await self.programs():
                raise CommandError("Unknown program")
            path, method, data = f"selprog/{program}", "POST", b""
            expected = IDLE
        elif action == "start":
            path, method, data = "start", "POST", {"delay_date": "0"}
            expected = {"PS_RUNNING"}
        elif action in ("stop", "pause", "continue"):
            path, method, data = (
                {"stop": "stop", "pause": "pause", "continue": "contin"}[action],
                "GET",
                None,
            )
            expected = {
                "stop": IDLE,
                "pause": {"PS_HOLDED"},
                "continue": {"PS_RUNNING"},
            }[action]
        else:
            raise CommandError("Unsupported operation")
        if action == "select" and before["progNumber"] == program:
            return {"controller": before}
        try:
            await self.request(
                f"/controller/{self.serial}/{path}", method=method, data=data
            )
        except AuthenticationError:
            raise
        except SuperwiseError as err:
            raise CommandError(
                "Command delivery uncertain; check controller before retrying"
            ) from err
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            state = await self.state()
            ctrl = state["controller"]
            if (
                ctrl["fresh"]
                and ctrl["lastActive"] > before["lastActive"]
                and ctrl["processStatus"] in expected
                and (action != "select" or ctrl["progNumber"] == program)
                and (
                    action != "stop"
                    or (ctrl["setpoint"] == 0 and ctrl.get("doValue") == 0)
                )
            ):
                return state
            await asyncio.sleep(1)
        raise CommandError(
            "Command result unconfirmed; check controller before retrying"
        )

    async def update_program(self, number, segment, changes):
        """Modify one segment, then require an explicit device readback."""
        await self.ensure_idle()
        original = await self.read_program(number)
        edited = deepcopy(original)
        if not 1 <= segment <= len(edited["segs"]):
            raise CommandError("Segment is outside the program")
        definition = edited["segDef"]
        for key, value in changes.items():
            if key not in ("value", "rtime", "dwell") or not isinstance(value, int):
                raise CommandError("Unsupported segment setting")
            # Ramp coding is not yet a stable physical-unit contract.
            if key == "rtime":
                raise CommandError("Ramp editing is not supported yet")
            if key == "dwell" and definition.get("tRes") != "TIME_RES_MIN":
                raise CommandError("Dwell editing requires minute-resolution programs")
            low, high = (
                (definition["vMin"], definition["vMax"])
                if key == "value"
                else (0, definition["dMax"] - 1)
            )
            if not low <= value <= high:
                raise CommandError("Segment setting is outside controller limits")
            edited["segs"][segment - 1][key] = value
        if not changes:
            raise CommandError("Specify a temperature or dwell setting")
        await self.ensure_idle()
        await self.request(
            f"/program/submit/{self.serial}",
            method="POST",
            data=json.dumps(edited, separators=(",", ":"), ensure_ascii=False),
            content_type="application/x-www-form-urlencoded; charset=UTF-8",
        )
        readback = await self.read_program(number)
        normalize = lambda p: {k: v for k, v in p.items() if k != "pcrc"}
        if normalize(readback) != normalize(edited):
            raise CommandError(
                "Program readback differs; inspect controller before any further write"
            )
        return {"program": readback, "previous_program": original, "verified": True}

    async def history(self, firing_id):
        records = await self.firings()
        record = next((f for f in records if f["id"] == firing_id), None)
        if not record:
            raise SuperwiseError("Unknown firing")
        start, end = record["startAt"], record["endAt"] or int(time.time() * 1000)
        if start is None:
            raise SuperwiseError("Firing has no start timestamp")
        curves = {}
        for sensor in ("IN0", "SP0", "LP0", "CJC"):
            try:
                curves[sensor] = json.loads(
                    await self.request(
                        f"/controller/{self.serial}/{sensor}/chartdata/{start}/{end}/0"
                    )
                )
            except ValueError as err:
                raise SuperwiseError("Invalid historical response") from err
        return {"firing": record, "curves": curves}
