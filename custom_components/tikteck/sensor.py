"""Tikteck diagnostic sensors (BLE signal strength of the connecting adapter)."""
from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import CONF_ADDRESS, EntityCategory, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TikteckConfigEntry
from .helpers import (
    ADAPTER_AUTO,
    CONF_ADAPTER,
    TELINK_COMPANY_ID,
    active_scanner,
    parse_telink_adv,
    scanner_devices,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TikteckConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TikteckRssiSensor(entry), TikteckFirmwareSensor(entry)])


class TikteckFirmwareSensor(SensorEntity):
    """Firmware version decoded passively from the bulb's advertisement.

    Needs no connection and no password: the version, provisioned flag, mesh node
    address and mesh id are all broadcast (docs/PROTOCOL.md §5). The firmware version
    also decides which reset path applies (power-cycle for <24, RF reset for >=24),
    surfaced as the ``reset_method`` attribute.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "firmware_version"
    _attr_name = "Firmware version"
    _attr_icon = "mdi:chip"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: TikteckConfigEntry) -> None:
        self._address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{self._address}_firmware"
        self._attr_native_value = None
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._address)}
        )

    def _manufacturer_data(
        self, service_info: bluetooth.BluetoothServiceInfoBleak | None
    ) -> dict[int, bytes] | None:
        """Best available manufacturer data, preferring a source with the FULL Telink block.

        ESPHome Bluetooth proxies only relay the first ~6 bytes of these bulbs'
        manufacturer data (company id + MAC) — the firmware/flags/mesh fields (offset 8+)
        are truncated. The host adapter sees the whole block. So gather every source that
        sees the bulb and pick the one whose company-529 payload is long enough to decode;
        fall back to any payload (so other code paths still see something).
        """
        candidates: list[dict[int, bytes]] = []
        if service_info is not None and service_info.manufacturer_data:
            candidates.append(service_info.manufacturer_data)
        for sd in scanner_devices(self.hass, self._address):
            if sd.advertisement and sd.advertisement.manufacturer_data:
                candidates.append(sd.advertisement.manufacturer_data)
        last = bluetooth.async_last_service_info(
            self.hass, self._address, connectable=False
        ) or bluetooth.async_last_service_info(self.hass, self._address, connectable=True)
        if last and last.manufacturer_data:
            candidates.append(last.manufacturer_data)
        for mfr in candidates:
            value = mfr.get(TELINK_COMPANY_ID)
            if value is not None and len(value) >= 13:
                return mfr
        return candidates[0] if candidates else None

    @callback
    def _refresh(self, service_info: bluetooth.BluetoothServiceInfoBleak | None) -> None:
        mfr = self._manufacturer_data(service_info)
        if mfr and 529 in mfr:
            _LOGGER.debug(
                "Tikteck %s: firmware refresh, 529 len=%d hex=%s",
                self._address, len(mfr[529]), mfr[529].hex(),
            )
        else:
            _LOGGER.debug("Tikteck %s: firmware refresh, mfr keys=%s", self._address, list(mfr) if mfr else None)
        info = parse_telink_adv(mfr)
        if info is None:
            # These bulbs alternate advert packets and only some carry the Telink
            # manufacturer block, so a packet without it is normal — keep the last
            # decoded value instead of flipping the sensor to unavailable.
            if self._attr_native_value is None:
                self._attr_available = False
            return
        self._attr_available = True
        self._attr_native_value = info["firmware"]
        self._attr_extra_state_attributes = {
            "provisioned": info["bound"],
            "mesh_node_address": f"0x{info['dev_addr']:04X}",
            "mesh_id": f"0x{info['mesh_id']:04X}",
            "reset_method": info["reset_method"],
            "product_type": info["product_type"],
            "product_subtype": info["product_subtype"],
        }

    @callback
    def _on_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        self._refresh(service_info)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._refresh(None)
        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._on_advertisement,
                bluetooth.BluetoothCallbackMatcher(address=self._address),
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )


class TikteckRssiSensor(SensorEntity):
    """Live BLE signal strength as seen by the adapter the bulb connects through.

    Needs no active connection — it reads the RSSI of the bulb's advertisements
    on the selected adapter/proxy (or, in Automatic mode, the proxies-first best
    one) and updates on every advertisement.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "signal_strength"
    _attr_name = "Signal strength"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: TikteckConfigEntry) -> None:
        self._address = entry.data[CONF_ADDRESS]
        self._preferred = entry.options.get(CONF_ADAPTER, ADAPTER_AUTO)
        self._attr_unique_id = f"{self._address}_rssi"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._address)}
        )

    @callback
    def _refresh(self) -> None:
        sd = active_scanner(self.hass, self._address, self._preferred)
        if sd is None:
            self._attr_native_value = None
            self._attr_available = False
            return
        self._attr_available = True
        self._attr_native_value = sd.advertisement.rssi
        self._attr_extra_state_attributes = {
            "adapter": sd.scanner.name,
            "adapter_source": sd.scanner.source,
        }

    @callback
    def _on_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        self._refresh()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._refresh()
        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._on_advertisement,
                bluetooth.BluetoothCallbackMatcher(address=self._address),
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )
