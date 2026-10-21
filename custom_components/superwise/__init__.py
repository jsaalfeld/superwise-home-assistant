"""Superwise cloud integration."""

from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import SuperwiseApi
from .const import CONF_COOKIES, CONF_POWER, CONF_SERIAL, CONF_URL, PLATFORMS
from .coordinator import SuperwiseCoordinator
from .services import async_register_services


async def async_setup_entry(hass, entry):
    # Reuse the session first; the coordinator renews it when necessary.
    if not entry.data.get(CONF_COOKIES) and not entry.data.get("password"):
        raise ConfigEntryAuthFailed("Sign in to create a session")
    api = SuperwiseApi(
        entry.data[CONF_URL],
        entry.data[CONF_SERIAL],
        entry.options.get(CONF_POWER, entry.data.get(CONF_POWER)),
        entry.data.get(CONF_COOKIES, []),
    )
    coordinator = SuperwiseCoordinator(hass, entry, api)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        async_register_services(hass)
        coordinator.start()
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    except BaseException:
        await coordinator.close()
        raise
    return True


async def async_reload_entry(hass, entry):
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or coordinator.options != dict(entry.options):
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.close()
    return unloaded
