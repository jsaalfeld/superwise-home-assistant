"""Common controller identity and timestamp-based availability."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SERIAL, CONF_URL, DOMAIN


class SuperwiseEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{key}"
        ctrl = coordinator.data["controller"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.unique_id)},
            name=ctrl.get("name") or "Superwise kiln",
            manufacturer="bentrup",
            model=ctrl.get("type"),
            serial_number=coordinator.entry.data[CONF_SERIAL],
            configuration_url=coordinator.entry.data[CONF_URL] + "/dashboard",
        )

    @property
    def available(self):
        return (
            super().available
            and not self.coordinator.authentication_lost
            and self.coordinator.data["controller"].get("fresh", False)
        )
