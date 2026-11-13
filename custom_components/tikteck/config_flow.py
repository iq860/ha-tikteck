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

from .const import CONF_MESH_ADDRESS, CONF_MESH_NAME, DOMAIN
from .helpers import (
    ADAPTER_AUTO,
    CONF_ADAPTER,
    adapter_choices,
    connection_candidates,
    detect_mesh_address,
)
from .protocol import (
    DEFAULT_MESH_NAME,
    TikteckAuthError,
    TikteckBulb,
    TikteckResetError,
    async_rf_reset,
)

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
        return await self.async_step_discovery_menu()

    async def async_step_discovery_menu(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Clicking 'Add' on a discovered bulb: set it up, or RF-reset it."""
        return self.async_show_menu(
            step_id="discovery_menu", menu_options=["configure", "recover"]
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=["configure", "recover"]
        )

    def _discovered_bulbs(self, include_configured: bool = False) -> dict[str, str]:
        """Tikteck bulbs currently seen, as {address: label} for a dropdown."""
        current = self._async_current_ids()
        found: dict[str, str] = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            if not _is_tikteck(info):
                continue
            if not include_configured and info.address in current:
                continue
            found[info.address] = f"{info.name} ({info.address})"
        return found

    async def async_step_configure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # Reached from a discovered-bulb 'Add' → the address is already known.
        if self._discovery is not None:
            self.context["address"] = self._discovery.address
            return await self.async_step_password()
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._discovery = None
            self.context["address"] = address
            return await self.async_step_password()

        self._found = self._discovered_bulbs()
        schema = vol.Schema(
            {vol.Required(CONF_ADDRESS): vol.In(self._found) if self._found else str}
        )
        return self.async_show_form(step_id="configure", data_schema=schema)

    async def async_step_recover(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick a bulb to RF-reset (works even on bulbs you can't log into)."""
        # Reached from a discovered-bulb 'Add' → the address is already known.
        if self._discovery is not None:
            self.context["recover_address"] = self._discovery.address
            return await self.async_step_rf_confirm()
        if user_input is not None:
            self.context["recover_address"] = user_input[CONF_ADDRESS]
            return await self.async_step_rf_confirm()

        # Configured bulbs are included: the owner may want to wipe one they already have.
        choices = self._discovered_bulbs(include_configured=True)
        schema = vol.Schema(
            {vol.Required(CONF_ADDRESS): vol.In(choices) if choices else str}
        )
        return self.async_show_form(step_id="recover", data_schema=schema)

    async def async_step_rf_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """RF-reset the bulb, then verify by pairing with the defaults and add it.

        Rather than stay silent after firing the reset frame, this re-pairs with the
        post-reset defaults (mesh 'Smart Light' / password '123'), and on success adds
        the bulb automatically so the whole recover → reset → pair → set-up sequence
        completes in one step. A reset that can't be confirmed is reported, not swallowed.
        """
        address = self.context["recover_address"]
        errors: dict[str, str] = {}
        if user_input is not None:
            ble_device = async_ble_device_from_address(self.hass, address, connectable=True)
            if ble_device is None:
                errors["base"] = "not_found"
            else:
                try:
                    ok, detail = await async_rf_reset(
                        ble_device,
                        address,
                        candidates=lambda: connection_candidates(self.hass, address),
                    )
                except TikteckResetError as err:
                    _LOGGER.warning("Tikteck %s: RF reset failed: %s", address, err)
                    errors["base"] = "rf_reset_failed"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Tikteck %s: RF reset error", address)
                    errors["base"] = "rf_reset_failed"
                else:
                    # The reply echo is unreliable (the bulb acks even when it doesn't
                    # reset), so the ground truth is whether it now pairs with the default
                    # password. Always verify, whatever the echo said.
                    _LOGGER.info(
                        "Tikteck %s: RF reset reply %s (success_discriminator=%s); verifying default pairing",
                        address, detail or "none", ok,
                    )
                    verified = await self._verify_default_login(address)
                    if verified:
                        _LOGGER.info(
                            "Tikteck %s: default pairing confirmed after reset — adding bulb", address
                        )
                        await self.async_set_unique_id(address, raise_on_progress=False)
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title=f"Tikteck {address}",
                            data={
                                CONF_ADDRESS: address,
                                CONF_PASSWORD: "123",
                                CONF_MESH_NAME: DEFAULT_MESH_NAME,
                            },
                        )
                    _LOGGER.warning(
                        "Tikteck %s: reset not confirmed — reply %s, default login failed", address, detail
                    )
                    errors["base"] = "rf_reset_unverified"
        return self.async_show_form(
            step_id="rf_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"address": address},
        )

    async def _verify_default_login(self, address: str, attempts: int = 4) -> bool:
        """After a reset, confirm the bulb accepts the default mesh/password ('123')."""
        for i in range(attempts):
            await asyncio.sleep(3)  # give the bulb time to reboot into the default mesh
            ble_device = async_ble_device_from_address(self.hass, address, connectable=True)
            if ble_device is None:
                _LOGGER.debug("Tikteck %s: default-login attempt %d — bulb not seen yet", address, i + 1)
                continue
            bulb = TikteckBulb(
                ble_device,
                "123",
                DEFAULT_MESH_NAME,
                candidates=lambda: connection_candidates(self.hass, address),
            )
            try:
                await bulb.test_login()
            except TikteckAuthError:
                _LOGGER.debug("Tikteck %s: default-login attempt %d rejected", address, i + 1)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Tikteck %s: default-login attempt %d error: %s", address, i + 1, err)
            else:
                _LOGGER.info("Tikteck %s: default login succeeded on attempt %d", address, i + 1)
                return True
        return False

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
        address = self.config_entry.data[CONF_ADDRESS]
        errors: dict[str, str] = {}
        if user_input is not None:
            options: dict[str, Any] = {CONF_ADAPTER: user_input[CONF_ADAPTER]}
            raw = str(user_input.get(CONF_MESH_ADDRESS, "")).strip()
            if raw:
                try:
                    options[CONF_MESH_ADDRESS] = int(raw.lower().removeprefix("0x"), 16)
                except ValueError:
                    errors["base"] = "bad_mesh_address"
            if not errors:
                # Blank clears it (back to broadcast).
                return self.async_create_entry(data=options)

        choices = adapter_choices(self.hass, address)
        current = self.config_entry.options.get(CONF_ADAPTER, ADAPTER_AUTO)
        if current not in choices:
            # chosen adapter not seen right now; keep it selectable
            choices[current] = f"{current} (not currently seen)"

        cur_addr = self.config_entry.options.get(
            CONF_MESH_ADDRESS, self.config_entry.data.get(CONF_MESH_ADDRESS)
        )
        detected = detect_mesh_address(self.hass, address)
        schema = vol.Schema(
            {
                vol.Required(CONF_ADAPTER, default=current): vol.In(choices),
                vol.Optional(
                    CONF_MESH_ADDRESS,
                    default="" if cur_addr is None else f"0x{cur_addr:04X}",
                ): str,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "detected": f"0x{detected:04X}" if detected is not None else "unknown (a proxy truncates the advert that carries it)"
            },
        )
