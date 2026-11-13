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

# Telink / Tikteck manufacturer-specific advertisement (company id 0x0211 = 529).
# Offsets validated on-air against a real bulb: the decoded mesh node address equals
# the low two bytes of the device MAC. See docs/PROTOCOL.md §5.
TELINK_COMPANY_ID = 529

# Firmware >= this value means the bulb will NOT reset on a power-cycle and needs the
# RF reset instead (docs/PROTOCOL.md §3).
RF_RESET_FIRMWARE = 24


def parse_telink_adv(manufacturer_data: dict[int, bytes] | None) -> dict | None:
    """Decode firmware/bound/address fields broadcast by the bulb — no connection needed.

    Returns None when the advertisement isn't a Telink block (or is too short). The
    returned dict is safe to expose as diagnostic state.
    """
    if not manufacturer_data:
        return None
    value = manufacturer_data.get(TELINK_COMPANY_ID)
    if not value or len(value) < 13:
        return None
    # value == the app's manu[] block starting at the repeated company-id pair, so the
    # jump-table offsets (manu[8]/manu[9]/manu[10]/manu[11:13]/manu[13:15]) land here.
    flags = value[8]
    firmware = flags >> 2
    return {
        "firmware": firmware,
        "bound": bool(flags & 0x01),
        "dev_addr": int.from_bytes(value[9:11], "little"),
        "mesh_id": int.from_bytes(value[11:13], "little"),
        "product_type": value[6],
        "product_subtype": value[7],
        "reset_method": "power_cycle" if firmware < RF_RESET_FIRMWARE else "rf_reset",
    }


def best_manufacturer_data(hass: HomeAssistant, address: str) -> dict[int, bytes] | None:
    """Manufacturer data from whichever source carries the FULL Telink block.

    ESPHome proxies relay only the first ~6 bytes, so prefer any scanner whose
    company-529 payload is long enough to decode (a host adapter); else return
    whatever is available.
    """
    candidates: list[dict[int, bytes]] = []
    for sd in scanner_devices(hass, address):
        if sd.advertisement and sd.advertisement.manufacturer_data:
            candidates.append(sd.advertisement.manufacturer_data)
    last = bluetooth.async_last_service_info(
        hass, address, connectable=False
    ) or bluetooth.async_last_service_info(hass, address, connectable=True)
    if last and last.manufacturer_data:
        candidates.append(last.manufacturer_data)
    for mfr in candidates:
        value = mfr.get(TELINK_COMPANY_ID)
        if value is not None and len(value) >= 13:
            return mfr
    return candidates[0] if candidates else None


def detect_mesh_address(hass: HomeAssistant, address: str) -> int | None:
    """The bulb's mesh node address decoded passively, if a full advert is available."""
    info = parse_telink_adv(best_manufacturer_data(hass, address))
    return info["dev_addr"] if info else None


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
