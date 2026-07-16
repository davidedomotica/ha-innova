"""Binary sensor: allarme del fancoil Innova."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: InnovaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(InnovaAlarm(coordinator, dev) for dev in coordinator.devices)


class InnovaAlarm(InnovaEntity, BinarySensorEntity):
    """Segnala se il fancoil ha un allarme attivo."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "alarm"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device, key="alarm")

    @property
    def available(self) -> bool:
        return super(InnovaEntity, self).available and self._st is not None

    @property
    def is_on(self) -> bool | None:
        return bool(self._st.alarm) if self._st else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        st = self._st
        if st and st.alarm_code:
            return {"code": st.alarm_code}
        return None
