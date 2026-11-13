"""Tikteck light entity."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_HS_COLOR, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.util.color as color_util

from . import TikteckConfigEntry

# Brightness calibration. The bulb's brightness byte is linear PWM, so a raw HA
# slider spends almost all its visible change in the bottom quarter. Map the
# slider (1-255) through a gamma curve onto a usable range so equal slider steps
# look like equal steps of light.
#   GAMMA   > 1 pushes more resolution to the low end (perceptual linearisation).
#   MIN_OUT the lowest byte that still lights the bulb (slider at 1).
#   MAX_OUT full output (slider at 255).
GAMMA = 2.2
MIN_OUT = 12
MAX_OUT = 255


def _calibrate(brightness: int) -> int:
    """HA brightness (0-255) -> bulb brightness byte (0, or MIN_OUT..MAX_OUT)."""
    if brightness <= 0:
        return 0
    frac = (brightness / 255) ** GAMMA
    return round(MIN_OUT + (MAX_OUT - MIN_OUT) * frac)


async def async_setup_entry(hass: HomeAssistant, entry: TikteckConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([TikteckLight(entry)])


class TikteckLight(LightEntity, RestoreEntity):
    _attr_assumed_state = True
    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_color_mode = ColorMode.HS
    _attr_supported_color_modes = {ColorMode.HS}

    def __init__(self, entry: TikteckConfigEntry) -> None:
        self._bulb = entry.runtime_data
        address = self._bulb.address
        self._attr_unique_id = address
        self._attr_is_on = False
        self._attr_brightness = 255
        self._attr_hs_color = (0.0, 0.0)
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            name=f"Tikteck {address[-5:]}",
            manufacturer="Tikteck",
            model="Smart Light (Telink BLE)",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == "on"
            if (b := last.attributes.get(ATTR_BRIGHTNESS)) is not None:
                self._attr_brightness = b
            if (hs := last.attributes.get(ATTR_HS_COLOR)) is not None:
                self._attr_hs_color = tuple(hs)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (hs := kwargs.get(ATTR_HS_COLOR)) is not None:
            self._attr_hs_color = hs
        if (b := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            self._attr_brightness = b
        r, g, b_ = color_util.color_hs_to_RGB(*self._attr_hs_color)
        await self._bulb.set_state(r, g, b_, _calibrate(self._attr_brightness))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._bulb.set_state(0, 0, 0, 0)
        self._attr_is_on = False
        self.async_write_ha_state()
