# Wansview / AJCloud — Home Assistant Integration

Unofficial custom integration for Home Assistant that supports **Wansview** cameras and any camera based on the **AJCloud** platform.

> ⚠️ This is an **unofficial, community-developed** integration. It is not affiliated with, endorsed by, or in violation of any policy of Wansview or AJCloud. It uses the same API protocol that the official Wansview mobile app uses to communicate with the AJCloud cloud service. No proprietary code is included.

---

## Features

- **Floodlight** — manual on/off control
- **Floodlight Auto** — enable/disable automatic trigger mode
- **Floodlight Mode** — select trigger: Disabled / Infrared auto / Smart light
- **Floodlight Duration** — configure auto-off duration (seconds)
- **Siren** — manual trigger
- **Motion Full View** — enable/disable full-viewport motion detection
- **Motion Sensitivity** — slider (0–5)
- **Camera** — live stream (RTSP) and snapshot
- **Online sensor** — connectivity status
- **Diagnostic sensors** — firmware version, WiFi RSSI, WiFi signal %, WiFi SSID, local IP

Multi-device supported: all cameras on the account are discovered automatically.

---

## Installation via HACS

1. In HACS → **Custom repositories** → add this repository URL → category **Integration**
2. Install **Wansview / AJCloud**
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Wansview/AJCloud**
5. Enter your Wansview app email and password

---

## Manual Installation

Copy the `custom_components/wansview` folder into your Home Assistant `custom_components` directory and restart.

---

## Requirements

- PyNaCl >= 1.5.0
- brotli >= 1.1.0

These are installed automatically by Home Assistant.

---

## Disclaimer

This integration is provided as-is with no warranty. It is not an official product of Wansview or AJCloud. Use at your own risk.
