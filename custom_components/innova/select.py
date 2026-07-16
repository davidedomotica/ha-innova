"""Heat-pump level and priority controls."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity

SILENT_LEVELS = {1: "off", 2: "auto", 3: "level_1", 4: "level_2", 5: "level_3", 6: "level_4"}
PRIORITIES = {1: "domestic_hot_water", 2: "zones"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: InnovaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []
    for device in coordinator.devices:
        status = coordinator.data.get(device.key)
        if not status or status.kind != "heatpump":
            continue
        if status.has_silent:
            entities.append(InnovaHeatPumpSelect(coordinator, device, "silent_level", SILENT_LEVELS))
        if status.load_priority is not None:
            entities.append(InnovaHeatPumpSelect(coordinator, device, "load_priority", PRIORITIES))
    async_add_entities(entities)


class InnovaHeatPumpSelect(InnovaEntity, SelectEntity):
    def __init__(self, coordinator, device, feature: str, values: dict[int, str]) -> None:
        super().__init__(coordinator, device, key=feature)
        self._feature = feature
        self._values = values
        self._attr_options = list(values.values())
        self._attr_translation_key = feature

    @property
    def current_option(self) -> str | None:
        if not self._st:
            return None
        value = self._st.silent_level if self._feature == "silent_level" else self._st.load_priority
        return self._values.get(value)

    async def async_select_option(self, option: str) -> None:
        value = next(key for key, label in self._values.items() if label == option)
        field = 5 if self._feature == "silent_level" else 6
        await self.coordinator.api.async_set_heatpump_option(self._device, field, value)
        await self.coordinator.async_request_refresh()
