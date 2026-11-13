"""Tikteck BLE bulbs (Bleak port of the removed core integration)."""
from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_MESH_ADDRESS, CONF_MESH_NAME
from .helpers import (
    ADAPTER_AUTO,
    CONF_ADAPTER,
    connection_candidates,
    default_mesh_address,
)
from .protocol import DEFAULT_MESH_NAME, TikteckBulb

PLATFORMS = [Platform.LIGHT, Platform.SENSOR]

type TikteckConfigEntry = ConfigEntry[TikteckBulb]


async def async_setup_entry(hass: HomeAssistant, entry: TikteckConfigEntry) -> bool:
    address = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(f"Tikteck bulb {address} not seen by any Bluetooth adapter/proxy")

    preferred = entry.options.get(CONF_ADAPTER, ADAPTER_AUTO)
    # Mesh command destination. Each lamp is its own light by DEFAULT: when the user
    # hasn't chosen anything we target the bulb's own node address. An explicit value
    # (a node address, or 0xFFFF to drive the whole mesh) overrides that.
    stored = entry.options.get(CONF_MESH_ADDRESS, entry.data.get(CONF_MESH_ADDRESS))
    mesh_address = stored if stored is not None else default_mesh_address(hass, address)
    bulb = TikteckBulb(
        ble_device,
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_MESH_NAME, DEFAULT_MESH_NAME),
        candidates=lambda: connection_candidates(hass, address, preferred),
        mesh_address=mesh_address,
    )

    # Reload the entry when the user changes the selected adapter in options.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    @callback
    def _update_device(service_info: bluetooth.BluetoothServiceInfoBleak, _change) -> None:
        bulb.set_ble_device(service_info.device)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _update_device,
            bluetooth.BluetoothCallbackMatcher(address=address, connectable=True),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )
    entry.runtime_data = bulb
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: TikteckConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TikteckConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.disconnect()
    return ok
