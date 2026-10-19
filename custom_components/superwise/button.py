"""Explicit kiln execution actions."""

from homeassistant.components.button import ButtonEntity

from .const import IDLE
from .entity import SuperwiseEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            SuperwiseButton(entry.runtime_data, key)
            for key in ("start", "stop", "pause", "continue")
        ]
    )


class SuperwiseButton(SuperwiseEntity, ButtonEntity):
    def __init__(self, coordinator, action):
        super().__init__(coordinator, action)
        self.action = action
        self._attr_translation_key = action
        self._attr_icon = {
            "start": "mdi:play",
            "stop": "mdi:stop",
            "pause": "mdi:pause",
            "continue": "mdi:play-pause",
        }[action]

    @property
    def available(self):
        if self.action == "stop":
            return (
                self.coordinator.last_update_success
                and not self.coordinator.authentication_lost
            )
        if not super().available or not self.coordinator.control_enabled:
            return False
        status = self.coordinator.data["controller"]["processStatus"]
        return (
            status
            in {"start": IDLE, "pause": {"PS_RUNNING"}, "continue": {"PS_HOLDED"}}[
                self.action
            ]
        )

    async def async_press(self):
        await self.coordinator.operation(self.action)
