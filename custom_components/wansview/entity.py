from __future__ import annotations

from typing import Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import WansviewDevice
from .const import DOMAIN
from .coordinator import WansviewDataUpdateCoordinator


class WansviewEntity(CoordinatorEntity[WansviewDataUpdateCoordinator]):
    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator)
        self._device = device

    @property
    def _dev(self) -> WansviewDevice:
        """Returns the most up-to-date device object from the last coordinator refresh."""
        return next(
            (d for d in self.coordinator.devices if d.device_id == self._device.device_id),
            self._device,
        )

    @property
    def device_info(self) -> dict[str, Any]:
        dev = self._dev
        info: dict[str, Any] = {
            "identifiers": {(DOMAIN, dev.device_id)},
            "name": dev.name,
            "manufacturer": "Wansview",
        }
        if dev.model:
            info["model"] = dev.model
        if dev.firmware_version:
            info["sw_version"] = dev.firmware_version
        return info
