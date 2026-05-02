from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import WansviewDevice
from .const import DOMAIN
from .coordinator import WansviewDataUpdateCoordinator
from .entity import WansviewEntity


SENSOR_PATHS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("Firmware", ("base", "fwVersion"), "mdi:chip"),
    ("Local IP", ("networkConfig", "localIp"), "mdi:ip-network"),
    ("WiFi SSID", ("networkConfig", "ssid"), "mdi:wifi"),
    ("Gateway IP", ("networkConfig", "gatewayIp"), "mdi:router-network"),
)


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
            for entity in _build_sensors(coordinator, device):
                if entity.unique_id in known:
                    continue
                known.add(entity.unique_id)
                new.append(entity)
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


def _build_sensors(
    coordinator: WansviewDataUpdateCoordinator,
    device: WansviewDevice,
) -> list[SensorEntity]:
    sensors: list[SensorEntity] = []
    if device.wifi_signal is not None:
        sensors.append(WansviewWifiSignalSensor(coordinator, device))
    if device.wifi_rssi is not None:
        sensors.append(WansviewWifiRssiSensor(coordinator, device))
    for name, path, icon in SENSOR_PATHS:
        if _value_at_path(device.raw.get("info", {}), path):
            sensors.append(WansviewInfoSensor(coordinator, device, name, path, icon))
    return sensors


class WansviewWifiSignalSensor(WansviewEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} WiFi Signal"
        self._attr_unique_id = f"{device.unique_id}_wifi_signal"

    @property
    def native_value(self) -> int | None:
        return self._dev.wifi_signal


class WansviewWifiRssiSensor(WansviewEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} WiFi RSSI"
        self._attr_unique_id = f"{device.unique_id}_wifi_rssi"

    @property
    def native_value(self) -> int | None:
        return self._dev.wifi_rssi


class WansviewInfoSensor(WansviewEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
        name: str,
        path: tuple[str, ...],
        icon: str,
    ) -> None:
        super().__init__(coordinator, device)
        self._path = path
        self._attr_icon = icon
        self._attr_name = f"{device.name} {name}"
        self._attr_unique_id = f"{device.unique_id}_{'_'.join(path)}"

    @property
    def native_value(self) -> str | int | float | None:
        value = _value_at_path(self._dev.raw.get("info", {}), self._path)
        if isinstance(value, (int, float, str)):
            return value
        return None


def _value_at_path(node: Any, path: tuple[str, ...]) -> Any:
    value = node
    for part in path:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            try:
                value = value[int(part) - 1]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return value
