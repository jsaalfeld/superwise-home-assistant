"""UI configuration and explicit session renewal."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import AuthenticationError, SuperwiseApi, SuperwiseError, validate_config
from .const import (
    CONF_CONTROL,
    CONF_COOKIES,
    CONF_POWER,
    CONF_SERIAL,
    CONF_URL,
    DEFAULT_URL,
    DOMAIN,
)


def credentials_schema(defaults=None):
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=defaults.get(CONF_URL, DEFAULT_URL)): str,
            vol.Required("username", default=defaults.get("username", "")): str,
            vol.Required("password"): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_SERIAL, default=defaults.get(CONF_SERIAL, "")): str,
            vol.Optional(CONF_POWER, default=defaults.get(CONF_POWER, 0)): vol.Coerce(
                float
            ),
        }
    )


async def authenticate(values):
    values = validate_config(values)
    api = SuperwiseApi(values[CONF_URL], values[CONF_SERIAL], values[CONF_POWER])
    try:
        await api.login(values["username"], values["password"])
        state = await api.state()
        values[CONF_COOKIES] = api.cookies()
        return values, state
    finally:
        await api.close()


class SuperwiseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                values = validate_config(user_input)
                await self.async_set_unique_id(
                    f"{values[CONF_URL]}:{values[CONF_SERIAL]}"
                )
                self._abort_if_unique_id_configured()
                # A second entry for the same account would compete for its session.
                if any(
                    e.data[CONF_URL] == values[CONF_URL]
                    and e.data["username"].casefold() == values["username"].casefold()
                    for e in self._async_current_entries()
                ):
                    return self.async_abort(reason="account_already_configured")
                values, state = await authenticate(values)
                return self.async_create_entry(
                    title=state["controller"].get("name", "Superwise"), data=values
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except SuperwiseError:
                errors["base"] = "cannot_connect"
            except ValueError as err:
                errors["base"] = str(err)
        return self.async_show_form(
            step_id="user", data_schema=credentials_schema(user_input), errors=errors
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            values = {**entry.data, **user_input}
            try:
                values, _ = await authenticate(values)
                return self.async_update_reload_and_abort(entry, data_updates=values)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except SuperwiseError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("password"): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SuperwiseOptionsFlow()


class SuperwiseOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                values = validate_config({**self.config_entry.data, **user_input})
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_POWER: values[CONF_POWER],
                        CONF_CONTROL: user_input[CONF_CONTROL],
                    },
                )
            except ValueError:
                errors["base"] = "invalid_power"
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POWER,
                        default=self.config_entry.options.get(
                            CONF_POWER, self.config_entry.data.get(CONF_POWER, 0)
                        ),
                    ): vol.Coerce(float),
                    vol.Required(
                        CONF_CONTROL,
                        default=self.config_entry.options.get(CONF_CONTROL, False),
                    ): bool,
                }
            ),
        )
