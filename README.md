# Tikteck for Home Assistant

Control **Tikteck / Telink BLE mesh LED bulbs** ("Smart Light", MAC prefix `00:21:4D`)
from Home Assistant over Bluetooth.

This is a modern rewrite of the original `tikteck` integration that was removed from
Home Assistant Core in 2022 when its `bluepy` dependency was dropped
([core#80286](https://github.com/home-assistant/core/issues/80286)). It keeps the
original login/encryption scheme but talks to the bulb through Home Assistant's own
Bluetooth stack ([Bleak] + [bleak-retry-connector]), so it works with:

- the host's Bluetooth adapter, **and**
- **ESPHome Bluetooth Proxies** (recommended for range)

[Bleak]: https://github.com/hbldh/bleak
[bleak-retry-connector]: https://github.com/Bluetooth-Devices/bleak-retry-connector

## Features

- UI config flow with automatic Bluetooth discovery — no YAML
- Tries every reachable adapter/proxy, **ESP proxies first**, and logs which one connected
- HS colour + brightness, with a perceptual (gamma) brightness curve so the slider
  tracks visible brightness instead of the bulb's raw linear PWM
- Connection is kept alive and reused, then dropped after idle

## Requirements

- Home Assistant 2024.8 or newer
- A Bluetooth adapter **or** an ESPHome Bluetooth Proxy within range of the bulb
- The bulb's **password**. The Tikteck app sets this per bulb; a factory-reset bulb
  falls back to the Telink default `123`. The mesh name is almost always `Smart Light`.

## Installation (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/iq860/ha-tikteck`, category **Integration**.
2. Install **Tikteck**, then restart Home Assistant.
3. **Settings → Devices & Services** → the bulb should appear as discovered, or
   **Add Integration → Tikteck**. Enter the password (you can paste a comma-separated
   list to try several, e.g. `123,1234,877503042`).

## Manual installation

Copy `custom_components/tikteck` into your HA `config/custom_components/` folder and
restart.

## Tuning

Brightness calibration lives at the top of `light.py` (`GAMMA`, `MIN_OUT`, `MAX_OUT`).
If very low settings go dark, raise `MIN_OUT`; if the curve feels off, adjust `GAMMA`.

## Notes & limitations

- These bulbs don't report state (`assumed_state`); HA shows the last commanded value.
- Old Telink bulbs connect best over a nearby ESP proxy; some host adapters (e.g. Intel
  on BlueZ) connect then abort (`le-connection-abort-by-local`).

## Credits

- Original protocol reverse-engineering: Matthew Garrett ([python-tikteck](https://github.com/mjg59/python-tikteck))
- Original Home Assistant integration authors
- Bleak rewrite and packaging: iq860

## License

[MIT](LICENSE)
