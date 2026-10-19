"""Kiln measurements and clearly labelled firing record timestamps."""

import time
from datetime import UTC, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature, UnitOfTime

from .entity import SuperwiseEntity

PARALLEL_UPDATES = 0
DESCRIPTIONS = (
    SensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="setpoint",
        translation_key="setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="heating_output",
        translation_key="heating_output",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heat-wave",
    ),
    SensorEntityDescription(
        key="estimated_power",
        translation_key="estimated_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="controller_temperature",
        translation_key="controller_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="process_status", translation_key="process_status", icon="mdi:state-machine"
    ),
    SensorEntityDescription(
        key="program_name",
        translation_key="program_name",
        icon="mdi:format-list-numbered",
    ),
    SensorEntityDescription(
        key="segment", translation_key="segment", icon="mdi:stairs"
    ),
    SensorEntityDescription(
        key="segment_remaining",
        translation_key="segment_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:timer-sand",
    ),
    SensorEntityDescription(
        key="last_contact",
        translation_key="last_contact",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="record_start",
        translation_key="record_start",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="last_record_duration",
        translation_key="last_record_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SuperwiseSensor(entry.runtime_data, d) for d in DESCRIPTIONS])


class SuperwiseSensor(SuperwiseEntity, SensorEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        data = self.coordinator.data
        ctrl = data["controller"]
        key = self.entity_description.key
        if key in ("temperature", "setpoint", "heating_output", "estimated_power"):
            return ctrl.get(
                {
                    "temperature": "value",
                    "setpoint": "setpoint",
                    "heating_output": "lpValue",
                    "estimated_power": "estimated_power_kw",
                }[key]
            )
        if key == "controller_temperature":
            if time.time() - data.get("sensors_at", 0) >= 60:
                return None
            return next(
                (
                    s.get("value")
                    for s in data.get("sensors", [])
                    if s.get("identifier") == "CJC"
                ),
                None,
            )
        if key == "process_status":
            return ctrl.get("processStatus")
        if key == "program_name":
            program = data.get("programs", {}).get(ctrl.get("progNumber"), {})
            return program.get("name")
        if key == "segment":
            raw = ctrl.get("segNumber")
            return (raw + 1) // 2 if raw is not None and 0 < raw < 200 else None
        if key == "segment_remaining":
            return (
                ctrl.get("remainingSegmentSeconds")
                if ctrl.get("processStatus")
                in ("PS_RUNNING", "PS_HOLDED", "PS_WAITSTART")
                else None
            )
        if key == "last_contact":
            stamp = ctrl.get("lastActive")
            return datetime.fromtimestamp(stamp / 1000, UTC) if stamp else None
        records = data.get("firings", [])
        if key == "record_start":
            stamp = records[0].get("startAt") if records else None
            return datetime.fromtimestamp(stamp / 1000, UTC) if stamp else None
        if key == "last_record_duration":
            for record in records:
                if (
                    record.get("endAt") is not None
                    and record.get("startAt") is not None
                ):
                    return max(0, (record["endAt"] - record["startAt"]) / 1000)
        return None

    @property
    def available(self):
        if not super().available:
            return False
        return self.native_value is not None

    @property
    def extra_state_attributes(self):
        key = self.entity_description.key
        if key == "estimated_power":
            return {"estimated": True, "rated_power_kw": self.coordinator.api.power}
        if key == "program_name":
            return {
                "program_number": self.coordinator.data["controller"].get("progNumber")
            }
        if key == "segment":
            return {
                "raw_segment": self.coordinator.data["controller"].get("segNumber"),
                "mode": self.coordinator.data["controller"].get("segmentMode"),
            }
        return None
