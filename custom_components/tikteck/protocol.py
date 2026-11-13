"""Tikteck (Telink) BLE protocol, ported from mjg59/python-tikteck (bluepy) to Bleak."""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

# Telink characteristic UUIDs (old bluepy code used handles 0x15 / 0x1b).
CHAR_COMMAND = "00010203-0405-0607-0809-0a0b0c0d1912"  # handle 0x15
CHAR_PAIR = "00010203-0405-0607-0809-0a0b0c0d1914"  # handle 0x1b

DEFAULT_MESH_NAME = "Smart Light"
DISCONNECT_DELAY = 120


def _encrypt(key: list[int] | bytes, data: list[int] | bytes) -> list[int]:
    enc = Cipher(algorithms.AES(bytes(reversed(bytes(key)))), modes.ECB()).encryptor()
    out = enc.update(bytes(reversed(bytes(data)))) + enc.finalize()
    return list(reversed(out))


def _name_pass_key(name: str, password: str) -> list[int]:
    n = name.ljust(16, "\0")[:16]
    p = password.ljust(16, "\0")[:16]
    return [ord(a) ^ ord(b) for a, b in zip(n, p)]


def generate_sk(name: str, password: str, data1: list[int], data2: list[int]) -> list[int]:
    return _encrypt(_name_pass_key(name, password), list(data1[:8]) + list(data2[:8]))


def key_encrypt(name: str, password: str, data: list[int]) -> list[int]:
    return _encrypt(data, _name_pass_key(name, password))


def encrypt_packet(sk: list[int], mac: list[int], packet: list[int]) -> list[int]:
    buf = [mac[0], mac[1], mac[2], mac[3], 0x01, packet[0], packet[1], packet[2], 15, 0, 0, 0, 0, 0, 0, 0]
    buf = _encrypt(sk, buf)
    for i in range(15):
        buf[i] ^= packet[i + 5]
    buf = _encrypt(sk, buf)
    packet[3] = buf[0]
    packet[4] = buf[1]

    iv = [0, mac[0], mac[1], mac[2], mac[3], 0x01, packet[0], packet[1], packet[2], 0, 0, 0, 0, 0, 0, 0]
    stream = _encrypt(sk, iv)
    for i in range(15):
        packet[i + 5] ^= stream[i]
    return packet


class TikteckAuthError(Exception):
    """Wrong mesh name / password."""


class TikteckBulb:
    """Async Tikteck bulb controller."""

    def __init__(
        self,
        ble_device: BLEDevice,
        password: str,
        name: str = DEFAULT_MESH_NAME,
        candidates: Callable[[], list[tuple[str, BLEDevice]]] | None = None,
    ) -> None:
        self._ble_device = ble_device
        # Returns [(adapter label, BLEDevice), ...] in the order to try.
        self._candidates = candidates
        self._password = password
        self._name = name
        self._mac = [int(x, 16) for x in reversed(ble_device.address.split(":"))]
        self._client: BleakClientWithServiceCache | None = None
        self._sk: list[int] | None = None
        self._seq = random.randrange(1, 0xFFFF)
        self._lock = asyncio.Lock()
        self._disconnect_timer: asyncio.TimerHandle | None = None

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        self._ble_device = ble_device

    @property
    def address(self) -> str:
        return self._ble_device.address

    async def _ensure_connected(self) -> None:
        if self._client and self._client.is_connected and self._sk:
            return
        options = self._candidates() if self._candidates else []
        if not options:
            options = [("default", self._ble_device)]
        last_err: Exception | None = None
        self._client = None
        for label, device in options:
            _LOGGER.debug("Tikteck %s: trying connection via %s", self.address, label)
            try:
                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    device,
                    self.address,
                    disconnected_callback=self._on_disconnect,
                    max_attempts=3,
                )
            except (BleakError, asyncio.TimeoutError, OSError) as err:
                _LOGGER.debug("Tikteck %s: connection via %s failed: %s", self.address, label, err)
                last_err = err
                continue
            _LOGGER.debug("Tikteck %s: connected via %s", self.address, label)
            break
        if self._client is None:
            raise last_err or BleakError("no adapter could connect")
        data = [0, 1, 2, 3, 4, 5, 6, 7, 0, 0, 0, 0, 0, 0, 0, 0]
        enc = key_encrypt(self._name, self._password, data)
        await self._client.write_gatt_char(CHAR_PAIR, bytes([0x0C] + data[:8] + enc[:8]), response=True)
        await asyncio.sleep(0.3)
        resp = await self._client.read_gatt_char(CHAR_PAIR)
        _LOGGER.debug("Tikteck %s: login response %s", self.address, resp.hex())
        if not resp or resp[0] != 0x0D:
            await self._client.disconnect()
            self._client = None
            raise TikteckAuthError(f"Login rejected by {self.address} (response {resp.hex()})")
        self._sk = generate_sk(self._name, self._password, data[:8], list(resp[1:9]))

    def _on_disconnect(self, _client) -> None:
        _LOGGER.debug("Disconnected from %s", self.address)
        self._sk = None

    def _reset_disconnect_timer(self) -> None:
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        loop = asyncio.get_running_loop()
        self._disconnect_timer = loop.call_later(
            DISCONNECT_DELAY, lambda: asyncio.ensure_future(self.disconnect())
        )

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None
        self._sk = None

    async def _send(self, command: int, data: list[int]) -> None:
        async with self._lock:
            for attempt in range(2):
                try:
                    await self._ensure_connected()
                    packet = [0] * 20
                    packet[0] = self._seq & 0xFF
                    packet[1] = (self._seq >> 8) & 0xFF
                    packet[5] = 0xFF  # msgid 0xffff low byte
                    packet[6] = 0xFF  # msgid | 0x80
                    packet[7] = command
                    packet[8] = 0x69
                    packet[9] = 0x69
                    packet[10:14] = data[:4]
                    enc = encrypt_packet(self._sk, self._mac, packet)
                    self._seq = self._seq + 1 if self._seq < 0xFFFF else 1
                    # Mesh light commands are fire-and-forget. Write WITHOUT response so a
                    # weak-signal link doesn't block on a per-packet ACK (much snappier on
                    # the brightness slider). Falls back inside the except below if the
                    # link is actually dead.
                    await self._client.write_gatt_char(CHAR_COMMAND, bytes(enc), response=False)
                    self._reset_disconnect_timer()
                    return
                except TikteckAuthError:
                    raise
                except (BleakError, asyncio.TimeoutError, OSError) as err:
                    _LOGGER.debug("Send to %s failed (attempt %s): %s", self.address, attempt + 1, err)
                    await self.disconnect()
                    if attempt:
                        raise

    async def test_login(self) -> None:
        async with self._lock:
            await self._ensure_connected()
        await self.disconnect()

    async def set_state(self, red: int, green: int, blue: int, brightness: int) -> None:
        await self._send(0xC1, [red, green, blue, brightness])

    async def set_default_state(self, red: int, green: int, blue: int, brightness: int) -> None:
        await self._send(0xC4, [red, green, blue, brightness])
