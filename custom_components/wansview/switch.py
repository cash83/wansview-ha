from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
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
        for d in coordinator.devices:
            if d.device_id not in known:
                known.add(d.device_id)
                if d.has_capability("siren"):
                    new.append(WansviewSirenSwitch(coordinator, d))
                if d.has_capability("floodlightTiming"):
                    new.append(WansviewFloodlightAutoSwitch(coordinator, d))
                if d.has_capability("detectEnhance"):
                    new.append(WansviewMotionFullViewportSwitch(coordinator, d))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class WansviewSirenSwitch(WansviewEntity, SwitchEntity):
    _attr_icon = "mdi:alarm-light"

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} Siren"
        self._attr_unique_id = f"{device.unique_id}_siren"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get(self._device.device_id, {}).get("siren")

    async def async_turn_on(self, **kwargs: Any) -> None:
        state = await self.coordinator.client.async_set_siren(self._dev, True)
        self.coordinator.data.setdefault(self._device.device_id, {})["siren"] = state
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        state = await self.coordinator.client.async_set_siren(self._dev, False)
        self.coordinator.data.setdefault(self._device.device_id, {})["siren"] = state
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()


class WansviewFloodlightAutoSwitch(WansviewEntity, SwitchEntity):
    _attr_icon = "mdi:motion-sensor"

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} Floodlight Auto"
        self._attr_unique_id = f"{device.unique_id}_floodlight_auto"

    @property
    def is_on(self) -> bool | None:
        return self._dev.floodlight_auto_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        # The standalone Auto switch means infrared/motion auto mode.
        await self.coordinator.client.async_set_floodlight_config(
            self._dev,
            auto_enabled=True,
            trigger="infrared",
        )
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_set_floodlight_config(
            self._dev,
            auto_enabled=False,
        )
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()


class WansviewMotionFullViewportSwitch(WansviewEntity, SwitchEntity):
    _attr_icon = "mdi:motion-sensor"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "raw_fullViewport": self._dev.detections_config.get("fullViewport"),
            "motion_sensitivity": self._dev.motion_sensitivity,
        }

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} Motion Full View"
        self._attr_unique_id = f"{device.unique_id}_motion_full_view"

    @property
    def is_on(self) -> bool:
        # Never return None here: in the device page Home Assistant renders an
        # unknown switch badly. If the cloud has not returned detectionsConfig
        # yet, show OFF until the next refresh instead of unknown.
        return bool(self._dev.motion_full_viewport)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_set_detections_config(
            self._dev,
            full_viewport=True,
        )
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_set_detections_config(
            self._dev,
            full_viewport=False,
        )
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()
