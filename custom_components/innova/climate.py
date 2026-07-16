"""Native climate entities for Innova AC, fancoil, thermostat and heat pump nodes."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    SWING_OFF,
    SWING_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import HvacUnitStatus, InnovaDevice
from .const import (
    DOMAIN,
    FAN_MODES,
    FAN_MODES_REV,
    MODE_AUTO,
    MODE_COOL,
    MODE_DRY,
    MODE_FAN,
    MODE_HEAT,
    OPERATION_MODES,
)
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity

MODE_TO_HVAC = {
    MODE_AUTO: HVACMode.AUTO,
    MODE_HEAT: HVACMode.HEAT,
    MODE_COOL: HVACMode.COOL,
    MODE_DRY: HVACMode.DRY,
    MODE_FAN: HVACMode.FAN_ONLY,
}
HVAC_TO_MODE = {value: key for key, value in MODE_TO_HVAC.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: InnovaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ClimateEntity] = []
    for device in coordinator.devices:
        status = coordinator.data.get(device.key)
        if status and status.kind == "heatpump":
            for unit in status.units:
                entities.append(InnovaHeatPumpClimate(coordinator, device, unit))
        else:
            entities.append(InnovaClimate(coordinator, device))
    async_add_entities(entities)


class InnovaClimate(InnovaEntity, ClimateEntity):
    """Comfort climate for AC, fancoil and thermostat devices."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: InnovaCoordinator, device: InnovaDevice) -> None:
        super().__init__(coordinator, device)
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if self._st and self._st.has_flap:
            features |= ClimateEntityFeature.SWING_MODE
        self._attr_supported_features = features

    @property
    def hvac_modes(self) -> list[HVACMode]:
        capabilities = self._st.mode_capabilities if self._st else set()
        modes = [MODE_TO_HVAC[item] for item in sorted(capabilities) if item in MODE_TO_HVAC]
        return [HVACMode.OFF, *(modes or [HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL])]

    @property
    def fan_modes(self) -> list[str]:
        capabilities = self._st.fan_capabilities if self._st else set()
        return [FAN_MODES[item] for item in sorted(capabilities) if item in FAN_MODES] or list(
            FAN_MODES.values()
        )

    @property
    def swing_modes(self) -> list[str] | None:
        return [SWING_ON, SWING_OFF] if self._st and self._st.has_flap else None

    @property
    def current_temperature(self) -> float | None:
        return self._st.room_temp if self._st else None

    @property
    def current_humidity(self) -> float | None:
        """Return the room humidity reported by the M7 thermostat."""
        return self._st.humidity if self._st else None

    @property
    def target_temperature(self) -> float | None:
        return self._st.setpoint if self._st else None

    @property
    def min_temp(self) -> float:
        return self._st.sp_min if self._st else 5.0

    @property
    def max_temp(self) -> float:
        return self._st.sp_max if self._st else 40.0

    @property
    def target_temperature_step(self) -> float:
        return self._st.sp_step if self._st else 0.5

    @property
    def hvac_mode(self) -> HVACMode:
        if not self._st or not self._st.power:
            return HVACMode.OFF
        return MODE_TO_HVAC.get(self._st.mode, HVACMode.AUTO)

    @property
    def fan_mode(self) -> str | None:
        return FAN_MODES.get(self._st.fan) if self._st else None

    @property
    def swing_mode(self) -> str | None:
        if not self._st or not self._st.has_flap:
            return None
        return SWING_ON if self._st.flap else SWING_OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._st
        return {
            "operation_mode": OPERATION_MODES.get(status.operation_mode, "unknown")
            if status
            else "unknown",
            "device_type": status.kind if status else "unknown",
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None or not self._st:
            return
        await self.coordinator.api.async_set_setpoint(
            self._device, self._st.kind, float(temperature)
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if not self._st:
            return
        api, kind = self.coordinator.api, self._st.kind
        if hvac_mode == HVACMode.OFF:
            await api.async_set_power(self._device, kind, False)
        else:
            await api.async_set_power(self._device, kind, True)
            await api.async_set_mode(self._device, kind, HVAC_TO_MODE.get(hvac_mode, MODE_AUTO))
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if self._st and fan_mode in FAN_MODES_REV:
            await self.coordinator.api.async_set_fan(
                self._device, self._st.kind, FAN_MODES_REV[fan_mode]
            )
            await self.coordinator.async_request_refresh()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        if self._st:
            await self.coordinator.api.async_set_flap(
                self._device, self._st.kind, swing_mode == SWING_ON
            )
            await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)


class InnovaHeatPumpClimate(InnovaEntity, ClimateEntity):
    """One climate entity for DHW and for each available heat-pump zone."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: InnovaCoordinator, device: InnovaDevice, unit: str) -> None:
        super().__init__(coordinator, device, key=unit)
        self._unit_name = unit
        self._attr_translation_key = f"heatpump_{unit}"

    @property
    def _unit(self) -> HvacUnitStatus | None:
        return self._st.units.get(self._unit_name) if self._st else None

    @property
    def hvac_modes(self) -> list[HVACMode]:
        if self._unit_name == "dhw":
            return [HVACMode.OFF, HVACMode.HEAT]
        return [HVACMode.OFF, HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL]

    @property
    def hvac_mode(self) -> HVACMode:
        if not self._unit or not self._unit.power:
            return HVACMode.OFF
        if self._unit_name == "dhw":
            return HVACMode.HEAT
        return MODE_TO_HVAC.get(self._st.mode, HVACMode.AUTO)

    @property
    def current_temperature(self) -> float | None:
        return self._unit.water_temp if self._unit else None

    @property
    def target_temperature(self) -> float | None:
        if not self._unit:
            return None
        if self._unit_name != "dhw" and self._st.mode == MODE_COOL:
            return self._unit.cooling_setpoint
        return self._unit.setpoint

    @property
    def min_temp(self) -> float:
        return self._unit.sp_min if self._unit else 5.0

    @property
    def max_temp(self) -> float:
        return self._unit.sp_max if self._unit else 40.0

    @property
    def target_temperature_step(self) -> float:
        return self._unit.sp_step if self._unit else 0.5

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self.coordinator.api.async_set_heatpump_unit(
            self._device,
            self._unit_name,
            setpoint=float(temperature),
            cooling=self._unit_name != "dhw" and self._st.mode == MODE_COOL,
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.api.async_set_heatpump_unit(
                self._device, self._unit_name, power=False
            )
        else:
            await self.coordinator.api.async_set_heatpump_unit(
                self._device, self._unit_name, power=True
            )
            if self._unit_name != "dhw":
                await self.coordinator.api.async_set_heatpump_mode(
                    self._device, HVAC_TO_MODE.get(hvac_mode, MODE_AUTO)
                )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT if self._unit_name == "dhw" else HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
