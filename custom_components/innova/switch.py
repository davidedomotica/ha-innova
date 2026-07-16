"""Optional Innova AC features represented as switches."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: InnovaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = []
    for device in coordinator.devices:
        status = coordinator.data.get(device.key)
        if status and status.kind == "ac":
            if status.has_silent:
                entities.append(InnovaFeatureSwitch(coordinator, device, "silent"))
            if status.has_erv:
                entities.append(InnovaFeatureSwitch(coordinator, device, "erv"))
    async_add_entities(entities)


class InnovaFeatureSwitch(InnovaEntity, SwitchEntity):
    def __init__(self, coordinator, device, feature: str) -> None:
        super().__init__(coordinator, device, key=feature)
        self._feature = feature
        self._attr_translation_key = feature

    @property
    def is_on(self) -> bool | None:
        if not self._st:
            return None
        return self._st.silent if self._feature == "silent" else self._st.erv

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        if self._feature == "silent":
            await self.coordinator.api.async_set_silent(self._device, enabled)
        else:
            await self.coordinator.api.async_set_erv(self._device, enabled)
        await self.coordinator.async_request_refresh()
