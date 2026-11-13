"""Pick which Bluetooth adapter/proxy to use, and read its signal."""
from __future__ import annotations

from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

try:
    from habluetooth import BaseHaRemoteScanner
except ImportError:  # pragma: no cover
    BaseHaRemoteScanner = ()  # type: ignore[assignment]

CONF_ADAPTER = "adapter"
ADAPTER_AUTO = "auto"


def scanner_devices(hass: HomeAssistant, address: str):
    """Connectable scanners that currently see the bulb, ESP proxies first then by RSSI."""
    found = bluetooth.async_scanner_devices_by_address(hass, address, connectable=True)

    def sort_key(sd):
        remote = isinstance(sd.scanner, BaseHaRemoteScanner) if BaseHaRemoteScanner else False
        return (0 if remote else 1, -(sd.advertisement.rssi or -127))

    return sorted(found, key=sort_key)


def active_scanner(hass: HomeAssistant, address: str, preferred_source: str | None = None):
    """The scanner the bulb connects through: the chosen one, else proxies-first best."""
    devices = scanner_devices(hass, address)
    if preferred_source and preferred_source != ADAPTER_AUTO:
        for sd in devices:
            if sd.scanner.source == preferred_source:
                return sd
        return None  # chosen adapter can't see the bulb right now
    return devices[0] if devices else None


def connection_candidates(
    hass: HomeAssistant, address: str, preferred_source: str | None = None
) -> list[tuple[str, BLEDevice]]:
    """Adapters to try, in order. A chosen adapter restricts to that one only."""
    devices = scanner_devices(hass, address)
    if preferred_source and preferred_source != ADAPTER_AUTO:
        chosen = [sd for sd in devices if sd.scanner.source == preferred_source]
        devices = chosen or devices  # fall back to auto if it's momentarily unseen
    return [
        (f"{sd.scanner.name} (rssi {sd.advertisement.rssi})", sd.ble_device)
        for sd in devices
    ]


def adapter_choices(hass: HomeAssistant, address: str) -> dict[str, str]:
    """Options-flow dropdown: automatic plus each adapter/proxy that sees the bulb."""
    choices = {ADAPTER_AUTO: "Automatic (Bluetooth proxies first)"}
    for sd in scanner_devices(hass, address):
        kind = "proxy" if (BaseHaRemoteScanner and isinstance(sd.scanner, BaseHaRemoteScanner)) else "local"
        choices[sd.scanner.source] = f"{sd.scanner.name} · {kind} · {sd.advertisement.rssi} dBm"
    return choices
