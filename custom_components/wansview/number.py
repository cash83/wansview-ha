from __future__ import annotations

import asyncio
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import WansviewDevice
from .const import DOMAIN
from .coordinator import WansviewDataUpdateCoordinator
from .entity import WansviewEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WansviewDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = []
        for device in coordinator.devices:
            if device.device_id in known:
                continue
            known.add(device.device_id)
            if device.has_capability("floodlightTiming"):
                new.append(WansviewFloodlightDurationNumber(coordinator, device))
            if device.has_capability("detectEnhance"):
                new.append(WansviewMotionSensitivityNumber(coordinator, device))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class WansviewFloodlightDurationNumber(WansviewEntity, NumberEntity):
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 300
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} Floodlight Duration"
        self._attr_unique_id = f"{device.unique_id}_floodlight_duration"

    @property
    def native_value(self) -> int | None:
        return self._dev.floodlight_duration

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.async_set_floodlight_config(
            self._dev,
            duration=int(value),
        )
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()


class WansviewMotionSensitivityNumber(WansviewEntity, NumberEntity):
    _attr_icon = "mdi:motion-sensor"
    _attr_native_min_value = 0
    _attr_native_max_value = 5
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} Motion Sensitivity"
        self._attr_unique_id = f"{device.unique_id}_motion_sensitivity"

    @property
    def native_value(self) -> int | None:
        return self._dev.motion_sensitivity

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.async_set_detections_config(
            self._dev,
            sensitivity=int(value),
        )
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()
