from __future__ import annotations

import asyncio
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import WansviewDevice
from .const import DOMAIN
from .coordinator import WansviewDataUpdateCoordinator
from .entity import WansviewEntity

FLOODLIGHT_MODE_TO_TRIGGER = {
    "Disattivato": None,
    "Infrarossi automatico": "infrared",
    "Luce intelligente": "action-detect",
}

MOTION_SENSITIVITY_TO_VALUE = {
    "Basso": 1,
    "Medio basso": 2,
    "Normale": 3,
    "Medio alto": 4,
    "Alto": 5,
}


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
                new.append(WansviewFloodlightModeSelect(coordinator, device))
            if device.has_capability("detectEnhance"):
                new.append(WansviewMotionSensitivitySelect(coordinator, device))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class WansviewFloodlightModeSelect(WansviewEntity, SelectEntity):
    _attr_options = list(FLOODLIGHT_MODE_TO_TRIGGER)
    _attr_icon = "mdi:lightbulb-auto"

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} Floodlight Mode"
        self._attr_unique_id = f"{device.unique_id}_floodlight_mode"

    @property
    def current_option(self) -> str | None:
        if self._dev.floodlight_auto_enabled is False:
            return "Disattivato"
        trigger = self._dev.floodlight_trigger
        for label, value in FLOODLIGHT_MODE_TO_TRIGGER.items():
            if value == trigger:
                return label
        return None

    async def async_select_option(self, option: str) -> None:
        trigger = FLOODLIGHT_MODE_TO_TRIGGER.get(option)
        if option == "Disattivato":
            await self.coordinator.client.async_set_floodlight_config(
                self._dev,
                auto_enabled=False,
            )
        elif trigger:
            await self.coordinator.client.async_set_floodlight_config(
                self._dev,
                auto_enabled=True,
                trigger=trigger,
            )
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()


class WansviewMotionSensitivitySelect(WansviewEntity, SelectEntity):
    _attr_options = list(MOTION_SENSITIVITY_TO_VALUE)
    _attr_icon = "mdi:motion-sensor"

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} Motion Sensitivity"
        self._attr_unique_id = f"{device.unique_id}_motion_sensitivity_select"

    @property
    def current_option(self) -> str | None:
        current = self._dev.motion_sensitivity
        if current is None:
            current = self.coordinator.data.get(self._device.device_id, {}).get(
                "motion_sensitivity",
                1,
            )
        for label, value in MOTION_SENSITIVITY_TO_VALUE.items():
            if value == current:
                return label
        return None

    async def async_select_option(self, option: str) -> None:
        value = MOTION_SENSITIVITY_TO_VALUE.get(option)
        if value is None:
            return
        await self.coordinator.client.async_set_detections_config(
            self._dev,
            sensitivity=value,
        )
        self.coordinator.data.setdefault(self._device.device_id, {})[
            "motion_sensitivity"
        ] = value
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()
