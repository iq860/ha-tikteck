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
- **Passive firmware/diagnostics** — a *Firmware version* sensor read straight from the
  bulb's advertisement (no connection, no password), with `mesh_node_address`, `mesh_id`,
  `provisioned` and a `reset_method` attribute telling you which reset the bulb needs
- **RF-reset recovery** — *Add Integration → Tikteck → Recover / reset a bulb* resets a
  bulb you can't log into (e.g. one still bound to another phone), unauthenticated, within
  the bulb's ~60 s post-power-on window

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
- **Each lamp is controlled on its own by default.** Bulbs that share a mesh name +
  password are one mesh; to keep them independent the integration addresses commands to
  each bulb's own node address (auto-derived; override per bulb under the integration's
  options). To drive the whole mesh from one entity, set that entity's mesh address to
  `all`. To control several lamps together, make a **Home Assistant *Light group* helper**
  from the individual lights (Settings → Devices & services → Helpers).
  - The auto node address is the bulb's passively-decoded address, falling back to the low
    byte of its MAC. If a lamp stops responding after an update, set its mesh address to
    `all` (or the correct hex node address) in the options.
- **The *Firmware version* sensor needs a full advertisement.** ESPHome Bluetooth proxies
  relay only the first ~6 bytes of these bulbs' manufacturer data (company id + MAC); the
  firmware/flags/mesh fields are truncated, so over a proxy-only setup the sensor reads
  *unavailable*. A host Bluetooth adapter in range sees the whole block and it populates.
- Old Telink bulbs connect best over a nearby ESP proxy; some host adapters (e.g. Intel
  on BlueZ) connect then abort (`le-connection-abort-by-local`).
- A **factory-reset** bulb falls back to mesh name `Smart Light` / password `123`. If you
  can't connect to a bulb, it is almost certainly still bound to another phone's mesh
  password — physically reset it first (power off, then toggle off/on 4×).

## Protocol / developer notes

See [`docs/PROTOCOL.md`](docs/PROTOCOL.md) for reverse-engineering notes on the Telink
mesh scheme: default credentials, the pairing/ownership model, the firmware-version and
"bound" flags readable **passively from the advertisement** (no connection), and the
factory/RF **reset command bytes**.

## Credits

- Original protocol reverse-engineering: Matthew Garrett ([python-tikteck](https://github.com/mjg59/python-tikteck))
- Original Home Assistant integration authors
- Bleak rewrite and packaging: iq860

## License

[MIT](LICENSE)
