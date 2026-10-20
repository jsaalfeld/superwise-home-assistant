"""Shared push state, periodic metadata and explicit authentication handling."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthenticationError, CommandError, SuperwiseError
from .const import CONF_CONTROL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SuperwiseCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, api):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=30),
        )
        self.entry = entry
        self.api = api
        self._metadata_at = 0.0
        self._stream_task = None
        self._unsub_tick = None
        self._operation_lock = asyncio.Lock()
        self.authentication_lost = False

    @property
    def control_enabled(self):
        return self.entry.options.get(CONF_CONTROL, False)

    async def _async_update_data(self):
        if self.authentication_lost:
            raise ConfigEntryAuthFailed("Session expired; explicit sign-in is required")
        try:
            state = await self.api.state()
            if self.data:
                state = {**self.data, **state}
            if not self.data or time.monotonic() - self._metadata_at >= 120:
                state["programs"] = await self.api.programs()
                state["firings"] = await self.api.firings()
                self._metadata_at = time.monotonic()
            return state
        except AuthenticationError as err:
            self.authentication_lost = True
            raise ConfigEntryAuthFailed(
                "Session expired; explicit sign-in is required"
            ) from err
        except SuperwiseError as err:
            raise UpdateFailed("Superwise update failed") from err

    def start(self):
        self._stream_task = self.hass.async_create_background_task(
            self._stream(), "superwise live updates"
        )
        self._unsub_tick = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=10)
        )

    async def _tick(self, now):
        if self.authentication_lost:
            return
        if self.data:
            ctrl = self.data["controller"]
            stamp = ctrl.get("lastActive")
            fresh = bool(stamp and 0 <= time.time() - stamp / 1000 < 60)
            if fresh != ctrl.get("fresh"):
                self.async_set_updated_data(
                    {**self.data, "controller": {**ctrl, "fresh": fresh}}
                )
        if time.monotonic() - self._metadata_at >= 120:
            await self.async_request_refresh()

    async def _stream(self):
        delay = 5
        while not self.authentication_lost:
            try:
                async for message in self.api.messages():
                    incoming = message["controller"]
                    existing = (self.data or {}).get("controller", {})
                    if incoming.get("lastActive", 0) < existing.get("lastActive", 0):
                        continue
                    if self.data:
                        self.async_set_updated_data(
                            {
                                **self.data,
                                "controller": {**existing, **incoming},
                                "sensors": message.get("sensors", []),
                                "sensors_at": time.time(),
                            }
                        )
                    delay = 5
            except AuthenticationError:
                self.authentication_lost = True
                self.async_set_update_error(ConfigEntryAuthFailed("Session expired"))
                self.entry.async_start_reauth(self.hass)
                return
            except (SuperwiseError, ValueError, KeyError):
                # Retain timestamp-based availability; a failed transport may recover.
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def operation(self, operation, **kwargs):
        if self.authentication_lost:
            raise HomeAssistantError("Sign in again before using the controller")
        if (
            operation not in ("stop", "read_program", "history", "list_firings")
            and not self.control_enabled
        ):
            raise HomeAssistantError(
                "Enable remote control in the integration options first"
            )
        async with self._operation_lock:
            try:
                if operation == "read_program":
                    return {"program": await self.api.read_program(kwargs["number"])}
                if operation == "update_program":
                    result = await self.api.update_program(**kwargs)
                    self._metadata_at = 0
                    await self.async_request_refresh()
                    return result
                if operation == "list_firings":
                    return await self.api.firings()
                if operation == "history":
                    return await self.api.history(kwargs["firing_id"])
                state = await self.api.command(operation, **kwargs)
                self.async_set_updated_data({**self.data, **state})
                return None
            except AuthenticationError as err:
                self.authentication_lost = True
                self.entry.async_start_reauth(self.hass)
                raise HomeAssistantError("Session expired; sign in again") from err
            except (CommandError, SuperwiseError) as err:
                # These exception messages are deliberately free of response bodies/secrets.
                raise HomeAssistantError(str(err)) from err

    async def close(self):
        if self._unsub_tick:
            self._unsub_tick()
        if self._stream_task:
            self._stream_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stream_task
        await self.api.close()
