"""Config flow for Tikteck."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import callback

from .const import CONF_MESH_NAME, DOMAIN
from .helpers import ADAPTER_AUTO, CONF_ADAPTER, adapter_choices, connection_candidates
from .protocol import DEFAULT_MESH_NAME, TikteckAuthError, TikteckBulb

_LOGGER = logging.getLogger(__name__)


def _is_tikteck(info: BluetoothServiceInfoBleak) -> bool:
    return 529 in info.manufacturer_data or info.name == DEFAULT_MESH_NAME or info.address.upper().startswith("00:21:4D")


class TikteckConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._found: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> TikteckOptionsFlow:
        return TikteckOptionsFlow()

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": f"{discovery_info.name} ({discovery_info.address})"}
        return await self.async_step_password()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._discovery = None
            self.context["address"] = address
            return await self.async_step_password()

        current = self._async_current_ids()
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address not in current and _is_tikteck(info):
                self._found[info.address] = f"{info.name} ({info.address})"
        schema = vol.Schema(
            {vol.Required(CONF_ADDRESS): vol.In(self._found) if self._found else str}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_password(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        address = self._discovery.address if self._discovery else self.context["address"]
        errors: dict[str, str] = {}
        if user_input is not None:
            ble_device = async_ble_device_from_address(self.hass, address, connectable=True)
            if ble_device is None:
                errors["base"] = "not_found"
            else:
                # A comma-separated list tries each password in turn.
                raw = user_input[CONF_PASSWORD]
                passwords = [p.strip() for p in raw.split(",")] if "," in raw else [raw]
                for pw in passwords:
                    bulb = TikteckBulb(
                        ble_device,
                        pw,
                        user_input[CONF_MESH_NAME],
                        candidates=lambda: connection_candidates(self.hass, address),
                    )
                    try:
                        await bulb.test_login()
                    except TikteckAuthError:
                        _LOGGER.debug("Tikteck %s: password %r rejected", address, pw)
                        errors["base"] = "invalid_auth"
                        await asyncio.sleep(1.5)
                        continue
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("Could not connect to %s", address)
                        errors["base"] = "cannot_connect"
                        break
                    _LOGGER.debug("Tikteck %s: password %r ACCEPTED", address, pw)
                    return self.async_create_entry(
                        title=f"Tikteck {address}",
                        data={
                            CONF_ADDRESS: address,
                            CONF_PASSWORD: pw,
                            CONF_MESH_NAME: user_input[CONF_MESH_NAME],
                        },
                    )
        schema = vol.Schema(
            {
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_MESH_NAME, default=DEFAULT_MESH_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="password", data_schema=schema, errors=errors,
            description_placeholders={"address": address},
        )


class TikteckOptionsFlow(OptionsFlow):
    """Let the user pick which Bluetooth adapter/proxy to use."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        address = self.config_entry.data[CONF_ADDRESS]
        choices = adapter_choices(self.hass, address)
        current = self.config_entry.options.get(CONF_ADAPTER, ADAPTER_AUTO)
        if current not in choices:
            # chosen adapter not seen right now; keep it selectable
            choices[current] = f"{current} (not currently seen)"
        schema = vol.Schema(
            {vol.Required(CONF_ADAPTER, default=current): vol.In(choices)}
        )
        return self.async_show_form(step_id="init", data_schema=schema)
