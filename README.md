# Tikteck for Home Assistant

Control **Tikteck / Telink Bluetooth “Smart Light” LED bulbs** from Home Assistant —
on/off, colour and brightness — with no phone app and no cloud.

These are the cheap colour BLE bulbs that pair with the old *Tikteck* / *Smart Light*
phone app. Their Bluetooth MAC address starts with `00:21:4D`. This integration brings
them back to Home Assistant after the original built-in `tikteck` integration was removed
from HA Core in 2022.

> **New here? Read these three sections and you’re done:**
> [Install](#1-install) → [Add your bulbs](#2-add-your-bulbs) → if a bulb won’t connect,
> [Reset a bulb you’re locked out of](#3-reset-a-bulb-youre-locked-out-of).

---

## What you get

- **Simple setup in the UI.** Bulbs are discovered automatically — no YAML, no config files.
- **Each bulb is its own light.** Turn one lamp on/off or change its colour without touching
  the others. Want several to move together? Group them with a normal Home Assistant
  *Light group* — see **[docs/GROUPING.md](docs/GROUPING.md)**.
- **Recover bulbs you’re locked out of.** A built-in *Recover / reset* flow wipes a bulb
  that’s still tied to someone else’s phone, so you can set it up fresh — see
  [section 3](#3-reset-a-bulb-youre-locked-out-of).
- **Works over range extenders.** Use your Home Assistant machine’s own Bluetooth, **or**
  an [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html) placed
  near the bulbs (recommended — these bulbs have weak radios).
- **Diagnostics.** Each bulb shows its Bluetooth signal strength, and (when a direct
  Bluetooth adapter is in range) its firmware version.

---

## Requirements

- Home Assistant **2024.8 or newer**.
- **Bluetooth within range of the bulbs** — either a Bluetooth adapter on the HA machine,
  or an ESPHome Bluetooth Proxy in the same room. These bulbs are short-range; a proxy
  nearby is the most reliable setup.
- For a bulb that was **already set up in the Tikteck app**, its password (a short number).
  A bulb that has never been paired — or one you reset with this integration — uses the
  default password **`123`**. You rarely need to type this yourself.

---

## 1. Install

### With HACS (recommended)

1. In Home Assistant, open **HACS**.
2. Top-right **⋮ → Custom repositories**.
3. Paste `https://github.com/iq860/ha-tikteck`, choose category **Integration**, click **Add**.
4. Find **Tikteck** in the list, click **Download**, then **restart Home Assistant**.

HACS will tell you when a new version is available so you can update with one click.

### Manually

Copy the `custom_components/tikteck` folder into your Home Assistant `config/custom_components/`
folder and restart Home Assistant.

---

## 2. Add your bulbs

1. Power on the bulb and make sure the phone app is **closed** (two apps can’t hold the
   bulb at once).
2. Go to **Settings → Devices & services**.
3. Your bulb usually appears by itself under **Discovered** as *Smart Light* — click **Add**.
   (If it doesn’t appear, click **+ Add integration**, search **Tikteck**, and pick it.)
4. Choose **Set up this bulb**.
5. Enter the password and click **Submit**:
   - If you set a password in the Tikteck app, use that.
   - If you don’t know it, try **`123`** (the default).
   - You can paste several to try at once, e.g. `123,1234,877503042`.
6. The bulb shows up as a light you can switch and colour. Repeat for each bulb.

**Can’t get past the password?** The bulb is almost certainly still “owned” by another
phone. Reset it — next section.

---

## 3. Reset a bulb you’re locked out of

Second-hand bulbs (and bulbs set up on someone else’s phone) stay locked to that phone’s
password. You can’t guess it, so you **reset** the bulb back to the default (`123`) and
set it up fresh.

These bulbs ignore the old “flick the switch 4 times” trick. This integration instead
sends a **radio reset** — but the bulb only accepts it in a short window right after it
powers on, **and only if the Bluetooth signal is strong**. That second part matters more
than anything else here.

### ⚠️ Proximity is the whole game

In testing, the exact same reset **failed** when the bulb was far from the Bluetooth
adapter/proxy (weak signal) and **succeeded** when it was close. The bulb will even *reply*
to a weak-signal attempt, so it looks like it worked — but it doesn’t actually reset.

**So before you reset: get the bulb and the Bluetooth adapter (or ESP proxy) close
together — ideally the same table, within a metre or two.** If your proxy is fixed in
place, bring the bulb (in a lamp or a desk socket) over to it for the reset, then move it
back afterwards.

### Steps

1. **Settings → Devices & services**, find the bulb under **Discovered**, click **Add**
   (or **+ Add integration → Tikteck**).
2. Choose **Recover / reset a bulb (RF reset)**, and pick the bulb if asked.
3. You’ll see a screen that says to power-cycle the bulb. **Don’t press Submit yet.**
4. Make sure the bulb is **close to the adapter/proxy**, then **switch the bulb fully OFF,
   then ON**.
5. **Within about 60 seconds** of it coming on, press **Submit**.
6. The integration resets the bulb, logs in with the default password, and — if it worked
   — **adds the bulb automatically**. The bulb usually blinks.

### If it says the reset wasn’t confirmed

That means the bulb didn’t truly reset (almost always weak signal or the 60-second window
closed). Just:

- Move the bulb **closer** to the adapter/proxy.
- Power it **off and on again**, and press **Submit** right away.

Repeat until it’s added. Once reset, the bulb’s password is `123` and you can set it up
normally.

---

## 4. One lamp vs. several together

By default **each bulb is controlled on its own**. That’s what most people want.

To control a few lamps as one (one switch, one colour for all), don’t change the
integration — make a standard **Home Assistant *Light group***. Full step-by-step,
including how to un-group and the advanced “control the whole mesh from one entity”
option, is in **[docs/GROUPING.md](docs/GROUPING.md)**.

---

## 5. Check it’s working

- Toggle a bulb in Home Assistant — only **that** bulb should react.
- Change its colour — the lamp should follow.
- Open the bulb’s device page to see its **Signal strength** (closer to `0` is stronger;
  `-90` and below is weak and unreliable).

---

## Troubleshooting

- **“Could not connect” / bulb keeps retrying.** The bulb is out of Bluetooth range or the
  signal is too weak. Move it closer to the adapter/proxy, or add an ESPHome Bluetooth
  Proxy in the same room. Also close the phone app.
- **“Bulb rejected the password.”** Wrong password, or the bulb is still locked to another
  phone. Try `123`, or [reset it](#3-reset-a-bulb-youre-locked-out-of).
- **A lamp stopped responding after an update.** Open the bulb’s integration **options**
  (gear icon) and set **Mesh address** to `all`, then **Submit**. See
  [docs/GROUPING.md](docs/GROUPING.md).
- **Changing one bulb changes several at once.** They’re being driven together. Open each
  bulb’s **options** and leave **Mesh address** blank (the default = this bulb only).
- **Firmware version shows “unavailable.”** Normal when the bulb is only reached through an
  ESPHome proxy — proxies don’t pass along the firmware data. A Bluetooth adapter on the HA
  machine in range will show it.
- **The light shows a state but the bulb is actually different.** These bulbs can’t report
  back, so Home Assistant shows the **last command** it sent. This is expected.

---

## Advanced

- **Choose a specific adapter/proxy.** Each bulb’s **options** (gear icon) let you pin it to
  one Bluetooth adapter or proxy instead of “Automatic”.
- **Brightness feel.** The brightness curve is tuned at the top of
  `custom_components/tikteck/light.py` (`GAMMA`, `MIN_OUT`, `MAX_OUT`). Raise `MIN_OUT` if
  the lowest setting goes dark.
- **How it all works under the hood** — the Telink/Tikteck Bluetooth protocol, default
  credentials, the reset mechanisms and the mesh addressing — is documented in
  **[docs/PROTOCOL.md](docs/PROTOCOL.md)**.

---

## Credits

- Original protocol reverse-engineering: Matthew Garrett
  ([python-tikteck](https://github.com/mjg59/python-tikteck))
- Original Home Assistant integration authors
- Bleak rewrite, recovery flow and per-bulb control: iq860

## License

[MIT](LICENSE)
