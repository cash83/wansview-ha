from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
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
                if d.has_capability("floodlight"):
                    new.append(WansviewFloodlight(coordinator, d))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class WansviewFloodlight(WansviewEntity, LightEntity):
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} Floodlight"
        self._attr_unique_id = f"{device.unique_id}_floodlight"

    @property
    def is_on(self) -> bool | None:
        cached = self.coordinator.data.get(self._device.device_id, {}).get("floodlight")
        if cached is not None:
            return cached
        return self._dev.floodlight_state

    async def async_turn_on(self, **kwargs: Any) -> None:
        state = await self.coordinator.client.async_set_floodlight(self._dev, True)
        self.coordinator.data.setdefault(self._device.device_id, {})["floodlight"] = state
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        state = await self.coordinator.client.async_set_floodlight(self._dev, False)
        self.coordinator.data.setdefault(self._device.device_id, {})["floodlight"] = state
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
