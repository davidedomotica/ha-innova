"""Diagnostica dell'integrazione Innova (senza credenziali)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import InnovaCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: InnovaCoordinator = hass.data[DOMAIN][entry.entry_id]
    statuses = {mac: asdict(st) for mac, st in coordinator.data.items()}
    for status in statuses.values():
        status["mode_capabilities"] = sorted(status["mode_capabilities"])
        status["fan_capabilities"] = sorted(status["fan_capabilities"])
    return {
        "devices": [asdict(d) for d in coordinator.devices],
        "status": statuses,
    }
