"""Select an existing controller program without starting it."""

from homeassistant.components.select import SelectEntity

from .const import IDLE
from .entity import SuperwiseEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SuperwiseProgram(entry.runtime_data)])


class SuperwiseProgram(SuperwiseEntity, SelectEntity):
    _attr_translation_key = "program"
    _attr_icon = "mdi:format-list-numbered"

    def __init__(self, coordinator):
        super().__init__(coordinator, "program")

    @property
    def options(self):
        return [
            f"{number:02d} — {p.get('name') or 'Program'}"
            for number, p in sorted(self.coordinator.data.get("programs", {}).items())
        ]

    @property
    def current_option(self):
        number = self.coordinator.data["controller"].get("progNumber")
        return next(
            (v for v in self.options if int(v.split(" — ", 1)[0]) == number), None
        )

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.control_enabled
            and self.coordinator.data["controller"]["processStatus"] in IDLE
        )

    async def async_select_option(self, option):
        await self.coordinator.operation(
            "select", program=int(option.split(" — ", 1)[0])
        )
