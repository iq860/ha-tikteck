"""Tikteck diagnostic sensors (BLE signal strength of the connecting adapter)."""
from __future__ import annotations

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
from .helpers import ADAPTER_AUTO, CONF_ADAPTER, active_scanner


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TikteckConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TikteckRssiSensor(entry)])


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
