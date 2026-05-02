from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from homeassistant.components.camera import Camera, CameraEntityFeature
try:
    from homeassistant.components.camera import StreamType
except ImportError:  # Older Home Assistant versions
    StreamType = None
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import WansviewDevice
from .const import DOMAIN
from .coordinator import WansviewDataUpdateCoordinator


def _plain_local_account_value(value: Any) -> str | None:
    """Return a local account field as plain text.

    Some firmware reports _encode=base64, but on several C1 devices the returned
    username/password values are already plain text. Try base64 only when it
    cleanly decodes to printable text; otherwise keep the original value.
    """
    if value is None:
        return None
    raw = str(value)
    if not raw:
        return None
    try:
        import base64

        decoded = base64.b64decode(raw, validate=True).decode("utf-8")
        if decoded and all(ch.isprintable() for ch in decoded):
            return decoded
    except Exception:
        pass
    return raw


def _stream_url(stream: dict[str, Any]) -> str | None:
    """Return the best URL for a stream entry."""
    url = stream.get("localUrl") or stream.get("wanUrl")
    return url if isinstance(url, str) and url else None


def _stream_url_for_device(device: WansviewDevice, stream: dict[str, Any]) -> str | None:
    """Build the RTSP URL per device using local IP, rtspConfig and local account.

    Wansview/AJCloud may report streamConfig.localUrl with the wrong/default port
    (:554) while the real active RTSP configuration is in rtspConfig.port
    (for example :557).  Build the URL from the device's own localIp + own
    credentials so multiple cameras do not share the wrong config.
    """
    info = device.raw.get("info", {}) if isinstance(device.raw, dict) else {}
    net_cfg = info.get("networkConfig", {}) if isinstance(info.get("networkConfig", {}), dict) else {}
    rtsp_cfg = info.get("rtspConfig", {}) if isinstance(info.get("rtspConfig", {}), dict) else {}
    account = info.get("localAccountConfig", {}) if isinstance(info.get("localAccountConfig", {}), dict) else {}

    raw_url = _stream_url(stream)
    parts = urlsplit(raw_url) if raw_url else None

    # Prefer the IP reported by the device info; fallback to the stream URL host.
    host_name = str(net_cfg.get("localIp") or (parts.hostname if parts else "") or "").strip()
    if not host_name:
        return raw_url

    # Prefer rtspConfig.port. If missing, fallback to URL port, then 554.
    port_raw = rtsp_cfg.get("port")
    try:
        port_int = int(port_raw) if port_raw not in (None, "") else (parts.port if parts else None)
    except (TypeError, ValueError):
        port_int = parts.port if parts else None
    if not port_int:
        port_int = 554

    # Channel/path: keep vendor path if present, otherwise build /live/ch0 from stream no=1.
    path = parts.path if parts and parts.path else ""
    if not path or path == "/":
        try:
            ch = max(int(stream.get("no") or 1) - 1, 0)
        except (TypeError, ValueError):
            ch = 0
        path = f"/live/ch{ch}"

    # Credentials are required when rtspConfig.verify=1.
    verify = str(rtsp_cfg.get("verify", "0")).lower() in {"1", "true", "yes", "on"}
    username = _plain_local_account_value(account.get("username"))
    password = _plain_local_account_value(account.get("password"))

    # If the original URL already contains credentials, preserve them.
    if parts and "@" in parts.netloc and parts.username:
        username = parts.username
        password = parts.password
        verify = True

    if ":" in host_name and not host_name.startswith("["):
        host_name = f"[{host_name}]"
    netloc = f"{host_name}:{port_int}"

    if verify and username and password is not None:
        netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{netloc}"

    return urlunsplit(("rtsp", netloc, path, parts.query if parts else "", parts.fragment if parts else ""))


def _quality_label(stream: dict[str, Any]) -> str:
    """Human friendly label for stream quality."""
    width = stream.get("resWidth")
    height = stream.get("resHeight")
    if height and width:
        return f"{width}x{height}"
    quality = str(stream.get("quality", ""))
    if quality == "6":
        return "2K"
    if quality == "5":
        return "FHD"
    if quality == "1":
        return "SD"
    return "Alta risoluzione"


def _quality_sort(stream: dict[str, Any]) -> tuple[int, int, int]:
    """Sort streams from best to worst."""
    try:
        height = int(stream.get("resHeight") or 0)
    except (TypeError, ValueError):
        height = 0
    try:
        width = int(stream.get("resWidth") or 0)
    except (TypeError, ValueError):
        width = 0
    try:
        quality = int(stream.get("quality") or 0)
    except (TypeError, ValueError):
        quality = 0
    return height, width, quality


def _best_stream(device: WansviewDevice) -> dict[str, Any] | None:
    """Return only the highest resolution RTSP stream for a device."""
    streams = [dict(s) for s in device.rtsp_streams if _stream_url_for_device(device, s)]
    if not streams:
        return None
    return sorted(streams, key=_quality_sort, reverse=True)[0]


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
            stream = _best_stream(device)
            if not stream:
                continue

            # Solo una camera per dispositivo: lo stream RTSP migliore / alta risoluzione.
            # Non vengono più create la camera snapshot principale né la camera SD.
            live_key = f"{device.device_id}:live:best"
            if live_key in known:
                continue
            known.add(live_key)
            new.append(WansviewHighResLiveCamera(coordinator, device, stream))

        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class WansviewHighResLiveCamera(Camera):
    """One fixed high-resolution RTSP live stream entity per Wansview device."""

    def __init__(
        self,
        coordinator: WansviewDataUpdateCoordinator,
        device: WansviewDevice,
        stream: dict[str, Any],
    ) -> None:
        Camera.__init__(self)
        self.coordinator = coordinator
        self._device = device
        self._stream = stream
        self._attr_supported_features = CameraEntityFeature.STREAM
        if StreamType is not None:
            self._attr_frontend_stream_type = StreamType.HLS

        label = _quality_label(stream)
        self._attr_name = f"{device.name} Live {label}"
        # Manteniamo lo stesso unique_id della vecchia camera alta risoluzione ch1,
        # così Home Assistant riusa l'entità già creata invece di crearne un'altra.
        no = stream.get("no") or "1"
        self._attr_unique_id = f"{device.unique_id}_camera_live_ch{no}"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    @property
    def _dev(self) -> WansviewDevice:
        return next(
            (d for d in self.coordinator.devices if d.device_id == self._device.device_id),
            self._device,
        )

    @property
    def available(self) -> bool:
        return self._dev.online and self.stream_source is not None

    @property
    def device_info(self) -> dict:
        dev = self._dev
        info = {
            "identifiers": {(DOMAIN, dev.device_id)},
            "name": dev.name,
            "manufacturer": "Wansview",
        }
        if dev.model:
            info["model"] = dev.model
        if dev.firmware_version:
            info["sw_version"] = dev.firmware_version
        return info

    async def stream_source(self) -> str | None:
        # Recalcola sempre il migliore dai dati aggiornati del coordinator.
        stream = _best_stream(self._dev) or self._stream
        return _stream_url_for_device(self._dev, stream)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        stream = _best_stream(self._dev) or self._stream
        attrs: dict[str, Any] = {}
        url = _stream_url_for_device(self._dev, stream)
        raw_url = _stream_url(stream)
        if raw_url:
            attrs["rtsp_live_url"] = raw_url
        info = self._dev.raw.get("info", {}) if isinstance(self._dev.raw, dict) else {}
        net_cfg = info.get("networkConfig", {}) if isinstance(info.get("networkConfig", {}), dict) else {}
        rtsp_cfg = info.get("rtspConfig", {}) if isinstance(info.get("rtspConfig", {}), dict) else {}
        if net_cfg.get("localIp"):
            attrs["rtsp_host"] = net_cfg.get("localIp")
        if rtsp_cfg.get("port"):
            attrs["rtsp_port"] = rtsp_cfg.get("port")
        if str(rtsp_cfg.get("verify", "0")) in {"1", "true", "True"}:
            attrs["rtsp_auth"] = "enabled"
        if stream.get("no"):
            attrs["channel"] = stream.get("no")
        if stream.get("quality"):
            attrs["quality"] = stream.get("quality")
        if stream.get("resWidth") and stream.get("resHeight"):
            attrs["resolution"] = f"{stream.get('resWidth')}x{stream.get('resHeight')}"
        if stream.get("frameRate"):
            attrs["frame_rate"] = stream.get("frameRate")
        return attrs

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        # Modalità LIVE-only: non forniamo più una still image al frontend.
        # Così la more-info/dialog del dispositivo non viene alimentata dallo
        # snapshot cloud e deve usare lo stream RTSP/HLS quando si apre la camera.
        return None
