"""Realtime v2 event streams with a periodic full-state safety poll."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import DeviceStatus, InnovaApi, InnovaAuthError, InnovaDevice, InnovaError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER


class InnovaCoordinator(DataUpdateCoordinator[dict[str, DeviceStatus]]):
    """Coordinates all devices belonging to one Innova account."""

    def __init__(
        self, hass: HomeAssistant, api: InnovaApi, devices: list[InnovaDevice], entry: ConfigEntry
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            config_entry=entry,
        )
        self.api = api
        self.devices = devices
        self._statuses: dict[str, DeviceStatus] = {}
        self._stream_tasks: list[asyncio.Task] = []
        self._closing = False

    async def _async_update_data(self) -> dict[str, DeviceStatus]:
        async def update(device: InnovaDevice) -> None:
            try:
                self._statuses[device.key] = await self.api.async_get_status(
                    device.mac, device.node_id
                )
            except InnovaAuthError:
                raise
            except InnovaError as err:
                LOGGER.debug("State unavailable for %s: %s", device.key, err)
                current = self._statuses.setdefault(device.key, DeviceStatus())
                current.online = False

        try:
            await asyncio.gather(*(update(device) for device in self.devices))
        except InnovaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        return self._statuses

    def start_streaming(self) -> None:
        """Open one event subscription per home, as required by AppService v2."""
        for home_id in sorted({device.home_id for device in self.devices if device.home_id}):
            self._stream_tasks.append(
                self.config_entry.async_create_background_task(
                    self.hass, self._stream_home(home_id), f"innova_stream_{home_id}"
                )
            )

    async def _stream_home(self, home_id: str) -> None:
        while not self._closing:
            try:
                async for mac, node_id, event in self.api.async_stream_events(home_id):
                    key = f"{mac}/{node_id}"
                    status = self._statuses.setdefault(key, DeviceStatus())
                    status.apply_event(event)
                    self.async_set_updated_data(self._statuses)
            except InnovaAuthError:
                try:
                    await self.api.async_login()
                except InnovaError:
                    pass
            except (InnovaError, httpx.HTTPError, asyncio.TimeoutError) as err:
                LOGGER.debug("Home event stream %s interrupted: %s", home_id, err)
            if not self._closing:
                await asyncio.sleep(5)

    async def async_shutdown(self) -> None:
        self._closing = True
        for task in self._stream_tasks:
            task.cancel()
        self._stream_tasks.clear()
        await super().async_shutdown()
