"""Integrazione Innova per Home Assistant (fancoil/termostati via cloud)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import InnovaApi, InnovaAuthError, InnovaError
from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN
from .coordinator import InnovaCoordinator

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura un account Innova."""
    api = InnovaApi(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    try:
        await api.async_login()
        devices = await api.async_get_devices()
    except InnovaAuthError as err:
        await api.async_close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except InnovaError as err:
        await api.async_close()
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = InnovaCoordinator(hass, api, devices, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    coordinator.start_streaming()  # aggiornamenti push in tempo reale
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Rimuove un account Innova."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: InnovaCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        await coordinator.api.async_close()
    return unloaded
