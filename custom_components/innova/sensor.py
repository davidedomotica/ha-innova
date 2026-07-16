"""Telemetry and operating-state sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPressure, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .api import DeviceStatus
from .const import DOMAIN, OPERATION_MODES
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity


@dataclass(frozen=True, kw_only=True)
class InnovaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[DeviceStatus], StateType]


SENSORS = (
    InnovaSensorDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda status: status.humidity,
    ),
    InnovaSensorDescription(
        key="operation_mode",
        translation_key="operation_mode",
        device_class=SensorDeviceClass.ENUM,
        options=list(OPERATION_MODES.values()),
        value_fn=lambda status: OPERATION_MODES.get(status.operation_mode, "unknown"),
    ),
    InnovaSensorDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda status: status.outdoor_temp,
    ),
    InnovaSensorDescription(
        key="water_pressure",
        translation_key="water_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda status: status.water_pressure,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: InnovaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[InnovaSensor] = []
    for device in coordinator.devices:
        status = coordinator.data.get(device.key)
        if status:
            entities.extend(
                InnovaSensor(coordinator, device, description)
                for description in SENSORS
                # M7 humidity can arrive only after setup through the live
                # event stream, so its entity must exist from the beginning.
                if (
                    description.key == "humidity" and status.kind != "heatpump"
                )
                or description.value_fn(status) is not None
            )
    async_add_entities(entities)


class InnovaSensor(InnovaEntity, SensorEntity):
    entity_description: InnovaSensorDescription

    def __init__(self, coordinator, device, description: InnovaSensorDescription) -> None:
        super().__init__(coordinator, device, key=description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self._st) if self._st else None
