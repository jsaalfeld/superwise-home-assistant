"""Response actions for controller program editing and historical curves."""

import math
import re

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


def whole_number(value):
    if (
        isinstance(value, float)
        and math.isfinite(value)
        and value >= 0
        and value.is_integer()
    ):
        return int(value)
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise vol.Invalid("Expected a nonnegative whole number")
    return int(value)


@callback
def async_register_services(hass):
    if hass.services.has_service(DOMAIN, "read_program"):
        return

    async def handle(call):
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if (
            not entry
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise HomeAssistantError("Select a loaded Superwise integration entry")
        coordinator = entry.runtime_data
        if call.service == "read_program":
            return await coordinator.operation(
                "read_program", number=call.data["program"]
            )
        if call.service == "update_program":
            changes = {}
            if "temperature" in call.data:
                changes["value"] = call.data["temperature"]
            if "dwell_minutes" in call.data:
                changes["dwell"] = call.data["dwell_minutes"]
            return await coordinator.operation(
                "update_program",
                number=call.data["program"],
                segment=call.data["segment"],
                changes=changes,
            )
        if call.service == "list_firings":
            return {"firings": await coordinator.operation("list_firings")}
        return await coordinator.operation("history", firing_id=call.data["firing_id"])

    base = {vol.Required("config_entry_id"): str}
    program = {
        **base,
        vol.Required("program"): vol.All(whole_number, vol.Range(min=1, max=99)),
    }
    hass.services.async_register(
        DOMAIN,
        "read_program",
        handle,
        schema=vol.Schema(program),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "update_program",
        handle,
        schema=vol.Schema(
            {
                **program,
                vol.Required("segment"): vol.All(whole_number, vol.Range(min=1)),
                vol.Optional("temperature"): whole_number,
                vol.Optional("dwell_minutes"): whole_number,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "list_firings",
        handle,
        schema=vol.Schema(base),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "get_firing_history",
        handle,
        schema=vol.Schema(
            {
                **base,
                vol.Required("firing_id"): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
