# Telink / Tikteck BLE mesh — protocol reverse-engineering notes

Developer reference for anyone extending this integration. These findings were
recovered by reverse-engineering a sibling app of the same device family — the
**Ledo Smart / "LedoBLE"** app (`com.skytone.LedoBle`), built on the same
Telink mesh stack (vendor framework: AppCan "ELBt" SDK, native lib
`libskytone-jni.so`, Java package `com.ledosmart.*`). The on-air scheme matches
this repo's `protocol.py` byte-for-byte (same `0x69 0x69` vendor marker, same
opcode-at-`packet[7]` layout, same name⊕password → AES session-key handshake),
so these notes apply directly to Tikteck bulbs.

> Scope: this documents a BLE LED bulb the author owns, for local control and
> factory-reset recovery. No cloud accounts, no third-party devices.

---

## 1. Device identity

| Property | Value | Notes |
|---|---|---|
| Default advertised name | `Smart Light` | `skName` constant; also this repo's `DEFAULT_MESH_NAME` |
| MAC OUI prefix | `00:21:4D` | Telink / Hangzhou Sky-tone |
| Advertising vendor (company) id | `0x0211` (529, little-endian `11 02`) | repeated **3×** inside the manufacturer-specific AD element |
| GATT service | `0x1910` | `NEW_SERVER_UUID`; old gen also exposes `0x1910` |
| Command characteristic | `00010203-0405-0607-0809-0a0b0c0d1912` (handle 0x15) | `CHAR_COMMAND` — encrypted mesh commands |
| Pair/notify characteristic | `...1914` (handle 0x1b) | `CHAR_PAIR` — login/handshake |
| Config chars (gen-dependent) | old `0x2b10` / `0x2b11`, new `0x0d0c` | used by the "RF" reset path |

---

## 2. Credentials & pairing model (why you can't just connect)

These are **Telink mesh** bulbs. Access is gated by a **mesh name + mesh
password** pair; from those two strings the app derives an AES session key
(`generate_sk` / `_name_pass_key` in `protocol.py`: `key[i] = name[i] ^ pw[i]`,
then AES).

**Factory / unprovisioned defaults** (from `LedoBleSDK.java`):

| Field | Default | Source constant |
|---|---|---|
| Mesh name | `Smart Light` | `skName` |
| Mesh password | `123` | `DEFAULT_PW` |
| LTK | *(none / stock Telink)* | `skLtk = null` |
| Factory mesh-net id | `10` | `MANUF_D_MESHNET_ID` |
| Factory product id | `2` | `MANUF_D_MESHPRO_ID` |

**Provisioning ("add device") flow:** the app connects to a fresh bulb as
`Smart Light` / `123`, then immediately calls `setKey(newPassword)` to overwrite
the mesh password with the **house/family secret**. That new password *is* the
"authorized code" the app's Family screen asks you to create and share. Once
written, only clients holding that password can derive the session key and
control the bulb — which is why a second phone/integration sees the bulb but
can't connect.

**Consequence:** you cannot software-reset or re-pair a bulb whose current
password you don't have (see §4). The escape hatch is the **physical reset**
(§3), which restores `Smart Light` / `123`.

---

## 3. Physical factory reset (no connection, no password needed)

From the app's (decrypted) `reset.html`, two procedures exist, selected by the
bulb's firmware `version`:

- **Firmware < 24 — pure hardware:** power the bulb on for ≥ 5 s, then switch it
  **off/on 4 times**. It blinks when reset.
- **Firmware ≥ 24 — timed app assist:** power it off, power on, and trigger the
  "Restore" within **1 minute** of power-on while close to it. During that
  post-boot window the bulb accepts the RF-reset command (§4.1) with default
  credentials.

Either way the bulb returns to **`Smart Light` / `123`**, ready to be adopted by
any client.

---

## 4. Reset commands (recovered from `libskytone-jni.so`)

Both reset paths ultimately require the native command builders below. The
payload is a 20-byte buffer; mesh commands are AES-encrypted with the session
key before the GATT write (`encrypt_packet` in this repo).

### 4.1 RF reset — `BTDataHandle_RfReset`  (the "Restore" button)

Java: `rfReset(mac, only_pwd)` → `uexELBtSDK.rfReset`. Builds a short
config-channel frame:

```
byte[0] = 0x69      # 'i'  ELBt config magic
byte[1] = 0x69      # 'i'
byte[2] = 0x11      # sub-command: RF reset
byte[3] = flag      # 0x00 = full restore (name+pwd+config)   <-- "Restore" uses this
                    # 0x01 = password-only reset
# length sent = 16 bytes (rest zero)
```

Success reply (`BTDataHandle_RfReset_result`): echoes `69 69 11 10`, with a
status byte at offset 4 (`0x37` observed as the ok/err discriminator).

> This is the path used right after power-on; it works while the bulb is briefly
> listening with default credentials, which is why timing/proximity matter.

### 4.2 Factory reset ("reset all") — `BTDataHandle_resetAll`

Java: `factoryReset(devAddr)` → `mainDev.sendData(senddata, /*encrypt=*/true, 2)`.
Device-targeted mesh command, **AES-encrypted** (`BTDataHandle_encryption_data`
is called before return):

```
byte[0..2] = seq       # 3-byte rolling sequence (global counter)
byte[3]    = 0x03
byte[4]    = 0x04
byte[5..6] = devAddr   # little-endian target mesh address
byte[7]    = 0xFC      # opcode  (sits immediately before the 69 69 vendor id,
                       #          exactly where protocol.py puts packet[7]=command)
byte[8]    = 0x69      # vendor id lo  }  == this repo's packet[8]/[9]
byte[9]    = 0x69      # vendor id hi  }
# remainder zero; 20 bytes total, then AES-ECB per encrypt_packet()
```

Requires an **authenticated** connection first (`isConnected()` guard), i.e. you
must already hold the bulb's current password. Confirms the "can't reset what you
can't connect to" limitation for the *software* path.

---

## 5. Passive detection from the advertisement (no connection) ⭐

The single most useful finding for this integration: **firmware version,
bound/used state, device address and mesh-net id are all broadcast in the
advertisement** and can be read during a passive scan — no GATT, no password.

Parsing (`SkBtDevice.Create` + native `BTDataHandle_manu_elem`): locate the
manufacturer-specific AD element whose **company id `0x0211`** appears (the app
scans for the 3rd occurrence of the `11 02` byte pair as the block start). Call
the start of that manufacturer block `manu[]`. Then:

| Field | Location in `manu[]` | Meaning |
|---|---|---|
| type | `manu[8]` | product type |
| sub-type | `manu[9]` | product sub-type |
| **bound / "used"** | `manu[10] & 0x01` | 1 = already provisioned to a mesh (not addable) |
| **firmware version** | `manu[10] >> 2` | 6-bit firmware version — the `version` the reset flow branches on (the "< 24 vs ≥ 24" test) |
| device address | `manu[11..12]` (u16 LE) | mesh node address |
| mesh-net id | `manu[13..14]` (u16 LE) | which mesh the bulb belongs to |

Byte offsets decoded from the `manu_elem` jump table in `libskytone-jni.so`
(element index → offset: 4→8, 5→9, 6→`[10]&1`, 7→`[10]>>2`, 9→`[11:13]`,
10→`[13:15]`).

**Integration opportunity:** a `firmware_version` sensor and a `bound`/`paired`
binary sensor could be populated **passively from `advertisement_data`** in the
config-flow / coordinator, without ever connecting — useful for diagnostics and
for telling the user whether a bulb still needs a physical reset. With nRF
Connect you can verify this by hand: read the manufacturer data for company
`0x0211` and apply the table above.

---

## 6. How these notes were obtained (methodology, for reproducibility)

The app ships 32-bit-ARM-only native libs (`lib/armeabi`, no arm64), so it can't
run on Apple-silicon emulators (`INSTALL_FAILED_NO_MATCHING_ABIS`). It was run
instead in **redroid** (containerised Android, no hypervisor) on an Ampere ARM
host whose CPU supports 32-bit EL0. Steps:

1. **Static:** `jadx` on `classes.dex` → `com.ledosmart.*` (credentials, flow),
   and `arm-linux-gnueabi-objdump -M force-thumb` on `libskytone-jni.so` for the
   reset builders and the advertisement parser (`BTDataHandle_manu_elem`).
2. **Assets:** the vendor framework (AppCan "3G2WIN Safe Guard") encrypts every
   HTML/JS asset (incl. `reset.html`) with a native RC4 keyed by an MD5 chain
   over the app's `appkey` resource + a 255-byte salt (`nativeHtmlDecode` in
   `libappcan.so`). Rather than reimplement it, the running app's WebView is
   debuggable — attach via Chrome DevTools over adb
   (`adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>`, CDP with
   `suppress_origin`) and read the already-decrypted DOM/JS.
3. **Cross-check:** confirmed the on-air command layout against this repo's
   existing `protocol.py` (independent port of `mjg59/python-tikteck`).

No Bluetooth radio exists in the container, so the reset commands were recovered
from code, not captured on-air. To validate end-to-end, capture an HCI snoop log
from a phone running the real app while it resets a bulb, and compare against
§4.

---

## 7. Open questions / next steps

- Confirm `0xFC` (factory) vs the control opcodes by diffing an HCI snoop log.
- Determine whether the RF-reset frame (§4.1) is written to `0x0d0c` (new gen)
  or `0x2b11` (old gen), and whether it is sent plaintext on the config channel.
- Implement passive `firmware_version` + `bound` sensors (§5).
- Map the remaining `com.ledosmart.ELBtBridge` native methods (timers, scenes,
  switch events) if timer/scene support is ever added here.
