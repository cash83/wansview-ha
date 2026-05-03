from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import WansviewClient, WansviewDevice
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class WansviewDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, client: WansviewClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=20),
        )
        self.client = client
        self.devices: list[WansviewDevice] = []

    async def _async_update_data(self) -> dict[str, Any]:
        self.devices = await self.client.async_devices()
        prev = self.data or {}
        data: dict[str, Any] = {}
        for device in self.devices:
            prev_dev = prev.get(device.device_id, {})
            data[device.device_id] = {
                "floodlight": device.floodlight_state,
                "night_mode": device.night_mode,
                "siren": device.siren_state,
                "motion_full_viewport": (
                    device.motion_full_viewport
                    if device.motion_full_viewport is not None
                    else prev_dev.get("motion_full_viewport")
                ),
                "motion_sensitivity": (
                    device.motion_sensitivity
                    if device.motion_sensitivity is not None
                    else prev_dev.get("motion_sensitivity", 1)
                ),
            }
        return data
