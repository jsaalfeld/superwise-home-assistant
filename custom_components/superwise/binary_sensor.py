"""Connection and active-process indication."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import ACTIVE
from .entity import SuperwiseEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            SuperwiseBinarySensor(entry.runtime_data, key)
            for key in ("connected", "active")
        ]
    )


class SuperwiseBinarySensor(SuperwiseEntity, BinarySensorEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self.key = key
        self._attr_translation_key = key
        self._attr_device_class = (
            BinarySensorDeviceClass.CONNECTIVITY
            if key == "connected"
            else BinarySensorDeviceClass.RUNNING
        )

    @property
    def available(self):
        return True if self.key == "connected" else super().available

    @property
    def is_on(self):
        if self.key == "connected":
            return (
                self.coordinator.last_update_success
                and not self.coordinator.authentication_lost
                and self.coordinator.data["controller"].get("fresh", False)
            )
        return self.coordinator.data["controller"].get("processStatus") in ACTIVE
