"""Base comune alle entita' Innova (device info, disponibilita')."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DeviceStatus, InnovaDevice
from .const import DOMAIN
from .coordinator import InnovaCoordinator


class InnovaEntity(CoordinatorEntity[InnovaCoordinator]):
    """Entita' legata a un fancoil Innova."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: InnovaCoordinator, device: InnovaDevice, key: str | None = None) -> None:
        super().__init__(coordinator)
        self._device = device
        mac_key = device.mac.replace(":", "").lower()
        node_key = f"_{device.node_id}" if device.node_id else ""
        self._attr_unique_id = f"{DOMAIN}_{mac_key}{node_key}" + (f"_{key}" if key else "")
        self._attr_device_info = DeviceInfo(
            # Preserve the v0.1 registry identifier for gateway/node 0 devices.
            identifiers={(DOMAIN, device.mac if device.node_id == 0 else device.key)},
            name=device.name or device.mac,
            manufacturer="Innova",
            model=f"Innova product {device.product_id}" if device.product_id else "Innova HVAC",
            serial_number=device.serial or None,
            suggested_area=device.room or None,
        )

    @property
    def _st(self) -> DeviceStatus | None:
        return self.coordinator.data.get(self._device.key)

    @property
    def available(self) -> bool:
        st = self._st
        return super().available and st is not None and st.online
