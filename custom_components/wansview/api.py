from __future__ import annotations

import asyncio
import base64
import brotli
import gzip
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientResponseError, ClientSession
from nacl.public import Box, PrivateKey, PublicKey

from .const import (
    DEFAULT_AGENT_MODEL,
    DEFAULT_AGENT_NAME,
    DEFAULT_APP_VERSION,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_LOCALE,
    DEFAULT_USER_AGENT,
    DEFAULT_VENDOR_CODE,
    NIGHT_MODE_MAP,
    NIGHT_MODE_REVERSE,
    REGION_EU,
    REGIONS,
)

_LOGGER = logging.getLogger(__name__)


class WansviewError(Exception):
    """Base API error."""


class WansviewAuthError(WansviewError):
    """Authentication failed."""


@dataclass(slots=True)
class WansviewDevice:
    device_id: str
    name: str
    raw: dict[str, Any]
    gateway_url: str | None = None

    @property
    def unique_id(self) -> str:
        return self.device_id

    @property
    def base_info(self) -> dict[str, Any]:
        return self.raw.get("info", {}).get("base", {})

    @property
    def capabilities(self) -> dict[str, str]:
        return self.raw.get("info", {}).get("capability", {})

    def has_capability(self, cap: str) -> bool:
        return self.capabilities.get(cap) == "1"

    @property
    def online(self) -> bool:
        if "onlineStatus" in self.base_info:
            return self.base_info.get("onlineStatus") == 2
        return self.raw.get("conStatus") == 1

    @property
    def firmware_version(self) -> str | None:
        return self.base_info.get("fwVersion") or self.raw.get("fwVersion") or None

    @property
    def model(self) -> str | None:
        return self.base_info.get("prodName") or self.raw.get("prodName") or None

    @property
    def wifi_signal(self) -> int | None:
        val = self.raw.get("info", {}).get("networkConfig", {}).get("wifiSignal")
        try:
            return int(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    @property
    def wifi_rssi(self) -> int | None:
        val = self.raw.get("info", {}).get("networkConfig", {}).get("wifiRssi")
        try:
            return int(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    @property
    def floodlight_state(self) -> bool | None:
        toggle = self.raw.get("info", {}).get("floodlightConfig", {}).get("toggle")
        if toggle == "on":
            return True
        if toggle == "off":
            return False
        return None


    @property
    def siren_state(self) -> bool | None:
        toggle = self.raw.get("info", {}).get("sirenConfig", {}).get("toggle")
        if toggle == "on":
            return True
        if toggle == "off":
            return False
        return None

    @property
    def snapshot_url(self) -> str | None:
        return self.base_info.get("snapshotUrl") or None

    @property
    def rtsp_streams(self) -> list[dict[str, Any]]:
        streams = self.raw.get("info", {}).get("streamConfig", {}).get("streams")
        return streams if isinstance(streams, list) else []

    @property
    def floodlight_brightness(self) -> int:
        val = self.raw.get("info", {}).get("floodlightConfig", {}).get("brightness")
        try:
            return int(val)
        except (TypeError, ValueError):
            return 1

    @property
    def floodlight_config(self) -> dict[str, Any]:
        config = self.raw.get("info", {}).get("floodlightConfig", {})
        return dict(config) if isinstance(config, dict) else {}

    @property
    def floodlight_auto_enabled(self) -> bool | None:
        val = self.floodlight_config.get("autoPolicy", {}).get("enable")
        if str(val) == "1" or val is True:
            return True
        if str(val) == "0" or val is False:
            return False
        return None

    @property
    def floodlight_trigger(self) -> str | None:
        triggers = self.floodlight_config.get("autoPolicy", {}).get("triggersOn")
        if isinstance(triggers, list) and triggers:
            return str(triggers[0])
        return None

    @property
    def floodlight_duration(self) -> int | None:
        val = self.floodlight_config.get("autoPolicy", {}).get("lightingDur")
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    @property
    def night_mode(self) -> str | None:
        val = self.base_info.get("nightMode")
        if val is not None:
            return NIGHT_MODE_MAP.get(str(val))
        return None

    @property
    def detections_config(self) -> dict[str, Any]:
        """Return the effective motion detection config.

        The API sometimes stores it directly as detectionsConfig and sometimes
        under detectionsConfig.share. The write endpoint expects the flattened
        object, so expose that normalized shape here.
        """
        config = self.raw.get("info", {}).get("detectionsConfig", {})
        if not isinstance(config, dict):
            return {}
        share = config.get("share")
        if isinstance(share, dict):
            return dict(share)
        return dict(config)

    @property
    def motion_sensitivity(self) -> int | None:
        val = self.detections_config.get("susceptiveness")
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    @property
    def motion_full_viewport(self) -> bool | None:
        val = self.detections_config.get("fullViewport")
        if str(val) == "1" or val is True:
            return True
        if str(val) == "0" or val is False:
            return False
        return None


class WansviewClient:
    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        region: str = REGION_EU,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._bases = REGIONS[region]
        self._agent_token = str(uuid.uuid4())

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._sign_token: str | None = None
        self._uid: str | None = None
        self._access_expires_at = 0.0
        self._country_code = DEFAULT_COUNTRY_CODE
        self._continent_code = ""

    async def async_login(self) -> None:
        had_session = bool(self._access_token and self._sign_token)
        if not had_session:
            self._agent_token = str(uuid.uuid4())
            self._access_token = None
            self._refresh_token = None
            self._sign_token = None
            self._uid = None
            self._access_expires_at = 0.0

        challenge = await self._request(
            "POST",
            f"{self._bases['uac']}/v3/outer-challenge",
            signed=had_session,
            payload={
                "data": {
                    "username": self._email,
                    "action": "signin",
                    "agentName": DEFAULT_AGENT_NAME,
                    "agentToken": self._agent_token,
                }
            },
        )

        result = challenge["result"]
        nonce = self._random_nonce()
        encrypted_password = self._encrypt_password(
            self._password,
            result["clientSecretKey"],
            result["serverPubKey"],
            nonce,
        )

        signin = await self._request(
            "POST",
            f"{self._bases['uac']}/v1/signin",
            signed=had_session,
            payload={
                "data": {
                    "username": self._email,
                    "password": encrypted_password,
                    "nonce": self._b64(nonce),
                    "agentName": DEFAULT_AGENT_NAME,
                    "modelName": DEFAULT_AGENT_MODEL,
                    "agentToken": self._agent_token,
                    "osName": "android",
                    "origin": "mobile phone",
                    "grantType": "password",
                    "scope": "all",
                }
            },
        )

        result = signin["result"]
        self._access_token = result["accessToken"]
        self._refresh_token = result["refreshToken"]
        self._sign_token = result["signToken"]
        self._uid = result["uid"]
        self._access_expires_at = time.time() + int(result.get("accessExpiresIn", 7200)) - 60
        ident = result.get("ident") or {}
        self._country_code = (ident.get("region") or self._country_code).upper()
        self._continent_code = ident.get("continent") or self._continent_code
        _LOGGER.debug(
            "Login ok | uid=%s country=%s continent=%s access_prefix=%s sign_prefix=%s",
            self._uid, self._country_code, self._continent_code,
            (self._access_token or "")[:12], (self._sign_token or "")[:12],
        )

    async def async_refresh_token(self) -> None:
        await self.async_login()

    async def async_devices(self) -> list[WansviewDevice]:
        await self._ensure_auth()
        data = await self._request(
            "POST",
            f"{self._bases['uac']}/v3/device-list",
            signed=True,
            payload={"data": {}},
        )

        raw_devices = self._merge_device_list(data.get("result") or {})
        devices = [self._device_from_raw(item) for item in raw_devices]
        return await self._async_add_device_infos(devices)

    async def async_set_floodlight(self, device: WansviewDevice, enabled: bool) -> bool:
        await self._ensure_auth()
        toggle = "on" if enabled else "off"
        brightness = int(device.floodlight_brightness or 1)
        await self._request(
            "POST",
            f"{self._bases['cam_gw']}/v1/floodlight-control",
            signed=True,
            device_id=device.device_id,
            payload={"data": {"toggle": toggle, "brightness": brightness}},
            base_url=device.gateway_url,
        )
        info = device.raw.setdefault("info", {})
        config = info.setdefault("floodlightConfig", {})
        if isinstance(config, dict):
            config["toggle"] = toggle
            config["brightness"] = str(brightness)
        return enabled

    async def async_set_floodlight_config(
        self,
        device: WansviewDevice,
        *,
        auto_enabled: bool | None = None,
        trigger: str | None = None,
        duration: int | None = None,
    ) -> None:
        await self._ensure_auth()
        config = device.floodlight_config
        auto_policy = dict(config.get("autoPolicy") or {})

        # AJCloud expects integers here, not strings. Keep the current trigger
        # when disabling, and only replace it when a specific mode is selected.
        if auto_enabled is not None:
            auto_policy["enable"] = 1 if auto_enabled else 0
        else:
            try:
                auto_policy["enable"] = int(auto_policy.get("enable", 0))
            except (TypeError, ValueError):
                auto_policy["enable"] = 0

        if trigger is not None:
            auto_policy["triggersOn"] = [trigger]
        elif not isinstance(auto_policy.get("triggersOn"), list):
            auto_policy["triggersOn"] = ["infrared"]

        if duration is not None:
            auto_policy["lightingDur"] = int(duration)
        else:
            try:
                auto_policy["lightingDur"] = int(auto_policy.get("lightingDur", 15))
            except (TypeError, ValueError):
                auto_policy["lightingDur"] = 15

        time_policies = config.get("timePolicies")
        if not isinstance(time_policies, list) or not time_policies:
            time_policies = [
                {"enable": 0, "endTime": "", "no": 1, "startTime": "", "toggle": "on", "weekDays": []},
                {"enable": 0, "endTime": "", "no": 2, "startTime": "", "toggle": "on", "weekDays": []},
            ]
        else:
            fixed = []
            for item in time_policies[:2]:
                item = dict(item)
                for key in ("enable", "no"):
                    try:
                        item[key] = int(item.get(key, 0))
                    except (TypeError, ValueError):
                        item[key] = 0
                item.setdefault("endTime", "")
                item.setdefault("startTime", "")
                item.setdefault("toggle", "on")
                item.setdefault("weekDays", [])
                fixed.append(item)
            while len(fixed) < 2:
                fixed.append({"enable": 0, "endTime": "", "no": len(fixed) + 1, "startTime": "", "toggle": "on", "weekDays": []})
            time_policies = fixed

        try:
            brightness = int(config.get("brightness", device.floodlight_brightness or 1))
        except (TypeError, ValueError):
            brightness = 1

        # Payload identical to the official Wansview/AJCloud app.
        # Important: do not send strings for enable/lightingDur/timePolicies.
        data = {
            "autoPolicy": {
                "enable": int(auto_policy.get("enable", 0)),
                "lightingDur": int(auto_policy.get("lightingDur", 15)),
                "triggersOn": list(auto_policy.get("triggersOn") or ["infrared"]),
            },
            "brightness": int(brightness),
            "timePolicies": time_policies,
            "toggle": "on" if str(config.get("toggle", "off")).lower() == "on" else "off",
        }
        _LOGGER.debug("Set floodlight-config %s: %s", device.device_id, data)
        await self._request(
            "POST",
            f"{self._bases['cam_gw']}/v1/floodlight-config",
            signed=True,
            device_id=device.device_id,
            payload={"data": data},
            base_url=device.gateway_url,
        )
        # Update local copy immediately so HA does not bounce back to the old mode
        # while the cloud propagates the change to fetch-infos.
        device.raw.setdefault("info", {})["floodlightConfig"] = data
        await asyncio.sleep(2.0)

    async def async_get_floodlight(self, device: WansviewDevice) -> bool | None:
        await self._ensure_auth()
        try:
            result = await self._request(
                "POST",
                f"{self._bases['cam_gw']}/v1/floodlight-config",
                signed=True,
                device_id=device.device_id,
                payload={"data": {}},
                base_url=device.gateway_url,
            )
        except WansviewError:
            return None
        found = self._find_first_key(result, {"toggle", "value", "enable", "enabled"})
        return self._parse_toggle(found)

    async def async_set_siren(self, device: WansviewDevice, enabled: bool) -> bool:
        await self._ensure_auth()
        toggle = "on" if enabled else "off"
        await self._request(
            "POST",
            f"{self._bases['cam_gw']}/v1/siren-control",
            signed=True,
            device_id=device.device_id,
            payload={"data": {"toggle": toggle}},
            base_url=device.gateway_url,
        )
        info = device.raw.setdefault("info", {})
        config = info.setdefault("sirenConfig", {})
        if isinstance(config, dict):
            config["toggle"] = toggle
        return enabled

    async def async_set_night_mode(self, device: WansviewDevice, mode: str) -> None:
        await self._ensure_auth()
        await self._request(
            "POST",
            f"{self._bases['cam_gw']}/v1/night-vision-config",
            signed=True,
            device_id=device.device_id,
            payload={"data": {"nightMode": NIGHT_MODE_REVERSE.get(mode, "0")}},
            base_url=device.gateway_url,
        )

    async def async_set_detections_config(
        self,
        device: WansviewDevice,
        *,
        sensitivity: int | None = None,
        full_viewport: bool | None = None,
    ) -> None:
        await self._ensure_auth()
        config = self._normalized_detections_config(device)
        if sensitivity is not None:
            sens = int(sensitivity)
            if sens < 1:
                sens = 1
            if sens > 5:
                sens = 5
            config["susceptiveness"] = str(sens)
            config["fullViewport"] = "1"
            config["areas"] = ["0,0,10000,10000"]
        if full_viewport is not None:
            config["fullViewport"] = "1" if full_viewport else "0"
            if full_viewport:
                config["areas"] = ["0,0,10000,10000"]
            else:
                config["areas"] = self._normalized_detection_areas(config.get("areas"))
        await self._request(
            "POST",
            f"{self._bases['cam_gw']}/v1/detections-config",
            signed=True,
            device_id=device.device_id,
            payload={"data": config},
            base_url=device.gateway_url,
        )
        device.raw.setdefault("info", {})["detectionsConfig"] = config

    def _normalized_detections_config(self, device: WansviewDevice) -> dict[str, Any]:
        config = dict(device.detections_config)
        data = {
            "susceptiveness": str(config.get("susceptiveness") or "2"),
            "deviceType": int(config.get("deviceType") or device.raw.get("deviceType") or 1),
            "areaShowStyle": str(config.get("areaShowStyle") or "0"),
            "areas": self._normalized_detection_areas(config.get("areas")),
            "fullViewport": "1" if str(config.get("fullViewport", "1")) == "1" else "0",
        }
        if data["fullViewport"] == "1":
            data["areas"] = ["0,0,10000,10000"]
        return data

    @staticmethod
    def _normalized_detection_areas(value: Any) -> list[str]:
        if isinstance(value, list):
            areas = [str(item) for item in value if str(item)]
            if areas:
                return areas
        return ["0,0,10000,10000"]

    async def _ensure_auth(self) -> None:
        if not self._access_token:
            await self.async_login()
        elif time.time() >= self._access_expires_at:
            await self.async_refresh_token()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        signed: bool,
        payload: dict[str, Any] | None = None,
        device_id: str | None = None,
        base_url: str | None = None,
        auth_header: bool = True,
        _retry: bool = True,
    ) -> dict[str, Any]:
        orig_url = url
        orig_payload = payload

        if base_url:
            path = "/" + url.split("://", 1)[1].split("/", 1)[1]
            if path.startswith("/api/"):
                path = path[4:]
            url = base_url.rstrip("/") + path

        built = self._with_meta(payload or {}, signed=signed, device_id=device_id)
        body = self._json(built)
        headers = self._headers()
        if signed:
            if not self._access_token or not self._sign_token:
                raise WansviewAuthError("Missing access/sign token")
            if auth_header:
                headers["Authorization"] = f"Bearer {self._access_token}"
            headers["X-UAC-Signature"] = self._signature(method, url, body)
            if "device-list" in url:
                path = "/" + url.split("://", 1)[1].split("/", 1)[1]
                _LOGGER.debug(
                    "Device-list signature debug | path=%s body_len=%s body_sha=%s "
                    "sig=%s access_prefix=%s sign_prefix=%s",
                    path,
                    len(body.encode("utf-8")),
                    hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    headers["X-UAC-Signature"],
                    self._access_token[:24],
                    self._sign_token[:12],
                )

        _LOGGER.debug(
            "Request %s %s | signed=%s auth_header=%s | token_prefix=%s",
            method, url, signed, auth_header,
            (self._access_token or "")[:12] if signed else "-",
        )

        async with self._session.request(method, url, data=body, headers=headers) as resp:
            try:
                resp.raise_for_status()
                raw = await resp.read()
            except ClientResponseError as err:
                raise WansviewError(f"HTTP error from AJCloud: {err.status}") from err

        content_encoding = resp.headers.get("Content-Encoding", "").lower()
        data = self._decode_json_response(raw, content_encoding, url)

        if data.get("status") != "ok" or data.get("code") not in (0, "0", None):
            msg = data.get("message") or f"AJCloud error: {data!r}"
            _LOGGER.warning(
                "AJCloud error | %s %s | code=%s status=%s | msg=%s | body=%s",
                method, url,
                data.get("code"), data.get("status"),
                msg, data,
            )
            is_auth_error = any(
                kw in msg.lower()
                for kw in ("token", "scadut", "expir", "unauthorized", "login", "auth")
            )
            if signed and _retry and is_auth_error and "device-list" not in url:
                _LOGGER.warning("Auth error, re-login and retry for %s", url)
                await self.async_login()
                return await self._request(
                    method, orig_url, signed=signed,
                    payload=orig_payload, device_id=device_id, base_url=base_url,
                    auth_header=auth_header,
                    _retry=False,
                )
            raise WansviewError(msg)
        return data

    def _headers(self) -> dict[str, str]:
        return {
            "Accept-Encoding": "br,gzip",
            "Accept-Language": "en-US,en;q=0.8",
            "Content-Type": "application/json;charset=utf-8",
            "User-Agent": DEFAULT_USER_AGENT,
            "x-agent-token": self._agent_token,
        }

    @staticmethod
    def _decode_json_response(
        raw: bytes,
        content_encoding: str,
        url: str,
    ) -> dict[str, Any]:
        def _loads(data: bytes) -> dict[str, Any]:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("utf-8", errors="replace")
            return json.loads(text)

        try:
            return _loads(raw)
        except json.JSONDecodeError:
            pass

        decoded = raw
        try:
            if content_encoding == "br":
                decoded = brotli.decompress(raw)
            elif content_encoding == "gzip" or raw[:2] == b"\x1f\x8b":
                decoded = gzip.decompress(raw)
            return _loads(decoded)
        except Exception as err:
            preview = raw[:240]
            raise WansviewError(
                f"Invalid response from AJCloud {url}: {preview!r}"
            ) from err

    def _signature(self, method: str, url: str, body: str) -> str:
        timestamp = str(int(time.time() * 1000) + 1000)
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        _LOGGER.debug("signature | path=%s body_hash=%s body_len=%d", path, body_hash[:16], len(body))
        sign_body = f"{method.upper()}\n{path}\n{body_hash}\n"
        string_to_sign = (
            "HMAC-SHA256\n"
            f"{timestamp}\n"
            f"{hashlib.sha256(sign_body.encode('utf-8')).hexdigest()}"
        )
        signature = hmac.new(
            self._sign_token.encode("utf-8"),
            string_to_sign.encode(),
            hashlib.sha256,
        ).digest()
        encoded = base64.b64encode(signature).decode("utf-8")
        encoded = encoded.replace("+", "-").replace("/", "_").replace("=", "")
        return f"UAC1-HMAC-SHA256;{timestamp};{encoded}"

    def _with_meta(
        self,
        payload: dict[str, Any],
        *,
        signed: bool = False,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        meta = {
                "locale": DEFAULT_LOCALE,
                "localtz": 60,
                "appName": "wansview",
                "appVersion": DEFAULT_APP_VERSION,
                "appVendorCode": DEFAULT_VENDOR_CODE,
                "agentName": DEFAULT_AGENT_NAME,
                "appCountryCode": self._country_code,
                "appContinentCode": self._continent_code,
        }
        if signed and self._access_token:
            meta["accessToken"] = self._access_token
        if device_id:
            meta["deviceId"] = device_id

        return {
            "meta": meta,
            **payload,
        }

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _b64(data: bytes) -> str:
        return base64.b64encode(data).decode("utf-8")

    @staticmethod
    def _random_nonce() -> bytes:
        return os.urandom(24)

    @staticmethod
    def _encrypt_password(
        password: str,
        client_secret_key_b64: str,
        server_public_key_b64: str,
        nonce: bytes,
    ) -> str:
        private_key = PrivateKey(base64.b64decode(client_secret_key_b64))
        public_key = PublicKey(base64.b64decode(server_public_key_b64))
        encrypted = Box(private_key, public_key).encrypt(
            password.encode(), nonce
        ).ciphertext
        return base64.b64encode(encrypted).decode("utf-8")

    @classmethod
    def _find_device_items(cls, node: Any) -> list[dict[str, Any]]:
        if isinstance(node, list):
            devices: list[dict[str, Any]] = []
            for item in node:
                if isinstance(item, dict) and cls._extract_device_id(item):
                    devices.append(item)
                else:
                    devices.extend(cls._find_device_items(item))
            return devices
        if isinstance(node, dict):
            devices = []
            for value in node.values():
                devices.extend(cls._find_device_items(value))
            return devices
        return []

    async def _async_add_device_infos(
        self,
        devices: list[WansviewDevice],
    ) -> list[WansviewDevice]:
        if not devices:
            return []

        gateway_url = next((device.gateway_url for device in devices if device.gateway_url), None)
        if not gateway_url:
            return devices

        payload_devices = [
            {
                "did": device.device_id,
                "scopes": [],
                "isShare": bool(device.raw.get("isShare", False) or device.raw.get("shares", 0)),
            }
            for device in devices
        ]

        try:
            data = await self._request(
                "POST",
                f"{self._bases['cam_gw']}/v1/fetch-infos",
                signed=True,
                payload={"data": {"devices": payload_devices}},
                base_url=gateway_url,
            )
        except WansviewError:
            return devices

        infos = data.get("result", {}).get("infos", [])
        if not isinstance(infos, list):
            return devices

        by_id = {device.device_id: dict(device.raw) for device in devices}
        for info_item in infos:
            if not isinstance(info_item, dict):
                continue
            device_id = self._extract_device_id(info_item) or info_item.get("did")
            if not device_id or device_id not in by_id:
                continue
            by_id[device_id].update(info_item)

        return [self._device_from_raw(by_id[device.device_id]) for device in devices]

    async def _async_add_detections_config(self, device: WansviewDevice) -> None:
        try:
            data = await self._request(
                "POST",
                f"{self._bases['cam_gw']}/v1/detections-config",
                signed=True,
                device_id=device.device_id,
                payload={"data": {}},
                base_url=device.gateway_url,
            )
        except WansviewError:
            return
        result = data.get("result")
        config = result if isinstance(result, dict) else data.get("data")
        if not isinstance(config, dict):
            return
        info = device.raw.setdefault("info", {})
        if isinstance(info, dict):
            info["detectionsConfig"] = config

    @classmethod
    def _merge_device_list(cls, result: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(result, dict):
            return []

        devices: dict[str, dict[str, Any]] = {}
        for key in ("conDevices", "devGenerals", "devCmpts", "devPinners"):
            items = result.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                device_id = cls._extract_device_id(item)
                if not device_id:
                    continue
                current = devices.setdefault(device_id, {})
                current.update(item)

        return list(devices.values())

    @classmethod
    def _device_from_raw(cls, raw: dict[str, Any]) -> WansviewDevice:
        device_id = cls._extract_device_id(raw)
        base = raw.get("info", {}).get("base", {})
        context = cls._parse_context(raw.get("context"))
        context_config = context.get("config", {}) if isinstance(context, dict) else {}
        if isinstance(context_config, str):
            context_config = cls._parse_context(context_config)

        name = (
            raw.get("aliasName")
            or base.get("aliasName")
            or raw.get("deviceName")
            or raw.get("name")
            or raw.get("nickName")
            or device_id
        )

        gateway_url = (
            raw.get("gatewayUrl")
            or raw.get("devGatewayUrl")
            or raw.get("appGatewayUrl")
            or raw.get("camGatewayUrl")
            or context_config.get("appGatewayUrl")
            or context_config.get("devGatewayUrl")
        )
        if not gateway_url:
            dispatch = base.get("dispatchUrl") or base.get("endpoint")
            if dispatch:
                if "://" not in dispatch:
                    dispatch = "https://" + dispatch
                # Keep only scheme+host+port, strip /api/... path
                gateway_url = dispatch.split("/api/")[0]

        return WansviewDevice(
            device_id=device_id,
            name=str(name).strip(),
            raw=raw,
            gateway_url=gateway_url or None,
        )

    @staticmethod
    def _parse_context(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str) or not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _extract_device_id(raw: dict[str, Any]) -> str:
        for key in ("deviceId", "devId", "dev_id", "cameraId", "id"):
            value = raw.get(key)
            if isinstance(value, str) and value:
                return value
        return ""

    @staticmethod
    def _parse_toggle(found: Any) -> bool | None:
        if isinstance(found, str):
            if found.lower() in {"on", "true", "1", "enabled"}:
                return True
            if found.lower() in {"off", "false", "0", "disabled"}:
                return False
        return bool(found) if found is not None else None

    @classmethod
    def _find_first_key(cls, node: Any, keys: set[str]) -> Any:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys:
                    return value
            for value in node.values():
                found = cls._find_first_key(value, keys)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = cls._find_first_key(value, keys)
                if found is not None:
                    return found
        return None
