"""Pick which Bluetooth adapters to try, ESPHome proxies first."""
from __future__ import annotations

from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

try:
    from habluetooth import BaseHaRemoteScanner
except ImportError:  # pragma: no cover
    BaseHaRemoteScanner = ()  # type: ignore[assignment]


def connection_candidates(hass: HomeAssistant, address: str) -> list[tuple[str, BLEDevice]]:
    found = bluetooth.async_scanner_devices_by_address(hass, address, connectable=True)

    def sort_key(sd):
        remote = isinstance(sd.scanner, BaseHaRemoteScanner) if BaseHaRemoteScanner else False
        return (0 if remote else 1, -(sd.advertisement.rssi or -127))

    return [
        (f"{sd.scanner.name} (rssi {sd.advertisement.rssi})", sd.ble_device)
        for sd in sorted(found, key=sort_key)
    ]
