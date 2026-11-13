# Telink / Tikteck BLE mesh — protocol reverse-engineering notes

Developer reference for anyone extending this integration. Findings were recovered by
reverse-engineering a sibling app of the same device family — the **Ledo Smart /
"LedoBLE"** app (`com.skytone.LedoBle`), built on the same Telink mesh stack (vendor
framework: AppCan "ELBt" SDK; native libs `libskytone-jni.so` + `libappcan.so`; Java
package `com.ledosmart.*`). The on-air scheme matches this repo's `protocol.py`
byte-for-byte (same `0x69 0x69` vendor marker, same opcode-at-`packet[7]` layout, same
name⊕password → AES session-key handshake), so these notes apply directly to Tikteck
bulbs.

> Scope: documenting a BLE LED bulb the author owns, for local control and
> factory-reset recovery. No cloud accounts, no third-party devices.

---

## 1. Device identity

| Property | Value | Notes |
|---|---|---|
| Default advertised name | `Smart Light` | `skName`; also this repo's `DEFAULT_MESH_NAME` |
| MAC OUI prefix | `00:21:4D` | Telink / Hangzhou Sky-tone |
| Advertising vendor (company) id | `0x0211` (529, LE `11 02`) | appears **3×** inside the manufacturer AD element |

### GATT map (`ELBtDev.java`)

Two services are used. The mesh service is tried in three UUID forms (new gen first):

| Service | UUID(s) | Purpose |
|---|---|---|
| **Mesh** | `19100d0c-0b0a-0908-0706-050403020100` → `00010203-0405-0607-0809-0a0b0c0d1910` → `00001910-0000-1000-8000-00805f9b34fb` | login + encrypted control |
| **SmartLight cmd** | `19200d0c-0b0a-0908-0706-050403020100` | RF-reset / "restore" channel |

Characteristics are matched by **GATT property bits**, not fixed UUIDs (so they vary by
generation). On the mesh service:

| Field | Property mask | Typical UUID | Role |
|---|---|---|---|
| `notifyChar` | `26` (0x1A notify) | — | status notifications |
| `rwChar` | `14` (0x0E write) | `...0d1912` (`CHAR_COMMAND`, handle 0x15) | encrypted mesh commands (`sendData(..., uuid=2)`) |
| `upgradeChar` | `6` | — | OTA |
| `pairChar` | `5` | `...0d1914` (`CHAR_PAIR`, handle 0x1b) | login handshake (`sendData(..., uuid=1)`) |
| `slCmdChar` | — | **`19210d0c-0b0a-0908-0706-050403020100`** (in service `1920`) | **RF reset target** |

---

## 2. Login handshake & encryption

Telink name/password scheme (already implemented in `protocol.py`):

1. `generate_sk` / `_name_pass_key`: `key[i] = name[i] ^ password[i]` (each padded to 16),
   then AES — yields the **session key `sk`**.
2. App writes a login request (`setTlLoginData(name, password, mac)`) to **`pairChar`**,
   then reads it back; the exchange derives `sk` for the connection.
3. All control commands are AES-encrypted with `sk` (`encrypt_packet`) and written to
   **`rwChar`**; status comes back on `notifyChar`.

Mesh command frame (20 bytes, before encryption) — `0x69 0x69` is the vendor id and the
byte right before it (`packet[7]`) is the **opcode**:

```
[0..1] seq   [2] 0  [3..4] sk-checksum  [5..6] msgid (0xFFFF = broadcast, or devAddr)
[7] opcode   [8..9] 0x69 0x69 vendor    [10..] params
```

**Factory / unprovisioned defaults** (`LedoBleSDK.java`):

| Field | Default | Constant |
|---|---|---|
| Mesh name | `Smart Light` | `skName` |
| Mesh password | `123` | `DEFAULT_PW` |
| LTK | *(stock Telink)* | `skLtk = null` |
| Factory mesh-net id | `10` | `MANUF_D_MESHNET_ID` |
| Factory product id | `2` | `MANUF_D_MESHPRO_ID` |

**Ownership model:** adding a bulb connects as `Smart Light`/`123`, then calls
`setKey(newPassword)` to overwrite the mesh password with the **house/family secret**
(the "authorized code" shared via the Family QR). Afterwards only clients holding that
password can derive `sk`. That is why a second phone/integration sees the bulb but can't
control it — and why the **encrypted** factory reset (§4.2) requires you to already know
the password.

---

## 3. Reset — the decision tree

There are **three** distinct reset mechanisms. Picking the right one is the whole game
for recovering a bulb whose password you don't have.

| Method | Needs password? | Needs connection? | When it works | Firmware |
|---|---|---|---|---|
| **Power-cycle** (§4.0) | No | No (pure hardware) | anytime | `< 24` |
| **RF reset** (§4.1) | **No** | Yes, but **no login** | **only within ~1 min of power-on** | `≥ 24` |
| **Factory reset / resetAll** (§4.2) | **Yes** | Yes, authenticated | anytime while connected | any |

**→ For a bulb you can't own/connect to, the RF reset (§4.1) is the key: it resets the
bulb WITHOUT its current password, because the firmware accepts it unauthenticated during
a short post-power-on window.** This is the most important finding in this document.

Firmware version is the branch selector and is **readable passively** (§5), so a client
can decide which path to offer before connecting.

---

## 4. Reset mechanisms in detail

### 4.0 Power-cycle (hardware, firmware < 24)

From the app's decrypted `reset.html`, exact wording:
- *"power on the bulb at least 5 seconds"*
- *"please turn off/on the bulb for 4 times to reset the bulb"*
- *"if bulb begin to blink, that means the bulb is restore succeed"*

Pure firmware behaviour; no BLE involved. If this isn't working for you, the bulb is very
likely **firmware ≥ 24**, which does **not** reset on power-cycles — it needs the RF reset
below instead.

### 4.1 RF reset — `BTDataHandle_RfReset` (the "Restore" button, firmware ≥ 24)

`reset.html` wording: *"power the bulb off and power it on again; move the smart phone
closer to the bulb, and click Restore **within 1 minute** after it power on; bulb will
finish restore after blinking."*

Code path: JS `reset()` → `bleReset(mac,false)` → `LedoBleSDK.rfReset(mac, only_pwd=false)`
→ `rfResetConnect()`. Crucially, `rfResetConnect` connects and, **on connect, calls
`tmpDev.rfReset()` with an EMPTY `loginCallback` — no authentication.** `ELBtDev.rfReset`
then writes a plaintext frame to **`slCmdChar` (`19210d0c-...`, service `1920`)** and reads
back after 500 ms:

```
byte[0] = 0x69      # 'i'  ELBt config magic
byte[1] = 0x69      # 'i'
byte[2] = 0x11      # sub-command: RF reset
byte[3] = flag      # 0x00 = full restore (name+pwd+config)   <-- "Restore" uses 0x00
                    # 0x01 = password-only reset
# 16 bytes sent, NOT encrypted
```

Success reply (`BTDataHandle_RfReset_result`): echoes `69 69 11 10`, status byte at
offset 4 (`0x37` = ok discriminator).

**Why it works without the password:** the write goes to the separate SmartLight command
characteristic, not the encrypted mesh `rwChar`, and the firmware only honours it during
the ~1-minute window after a cold boot. That window + physical power access *is* the
security model (you must be present and quick), which is exactly what lets a legitimate
owner recover a bulb they were locked out of.

**HA integration recipe (recommended feature):**
1. Ask the user to power-cycle the bulb (off, then on).
2. Immediately connect (Bleak) to the bulb — **no login/pairing**.
3. Discover service `19200d0c-...`, characteristic `19210d0c-...`.
4. `write_gatt_char(0x1921…, bytes([0x69,0x69,0x11,0x00] + [0]*12), response=False)`.
5. Optionally read back and check for `69 69 11 10`. Must complete inside ~60 s of boot.

### 4.2 Factory reset ("reset all") — `BTDataHandle_resetAll`

`factoryReset(devAddr)` → guarded by `isConnected()` → `mainDev.sendData(data, enc=true, 2)`.
Device-targeted mesh command, **AES-encrypted** (`BTDataHandle_encryption_data` before
send):

```
[0..2] seq   [3] 0x03  [4] 0x04  [5..6] devAddr (LE)
[7] 0xFC opcode   [8..9] 0x69 0x69 vendor   (20 bytes, then AES-ECB)
```

Requires a logged-in session (you must hold the current password). Use when you *do* own
the bulb and want a clean wipe.

> There is also a `BTDataHandle_reboot` builder (soft reboot, opcode byte at `[7]`),
> distinct from reset — it restarts the bulb without clearing credentials.

---

## 5. Passive detection from the advertisement (no connection) ⭐

Firmware version, bound/used state, device address and mesh-net id are all **broadcast**
and readable in a passive scan — no GATT, no password.

Parsing (`SkBtDevice.Create` + native `BTDataHandle_manu_elem`): find the
manufacturer-specific AD element for **company id `0x0211`** (the app keys off the 3rd
occurrence of the `11 02` pair as block start). Call that block `manu[]`:

| Field | Location in `manu[]` | Meaning |
|---|---|---|
| type | `manu[8]` | product type |
| sub-type | `manu[9]` | product sub-type |
| **bound / "used"** | `manu[10] & 0x01` | 1 = provisioned to a mesh (not addable) |
| **firmware version** | `manu[10] >> 2` | 6-bit version; the `< 24` vs `≥ 24` reset selector |
| device address | `manu[11..12]` (u16 LE) | mesh node address |
| mesh-net id | `manu[13..14]` (u16 LE) | which mesh it belongs to |

Offsets decoded from the `manu_elem` jump table in `libskytone-jni.so` (element→offset:
4→8, 5→9, 6→`[10]&1`, 7→`[10]>>2`, 9→`[11:13]`, 10→`[13:15]`).

**Integration opportunity:** expose `firmware_version` + a `bound` binary sensor from
`advertisement_data` with no connection. Combined with §3 this lets the UI tell the user
up front whether a bulb needs a power-cycle reset (<24) or an RF reset (≥24), and whether
it's already claimed by another mesh.

---

## 6. Command surface (native `BTDataHandle_*`, for future feature work)

Control/state commands build the mesh frame of §2 (vendor `0x69 0x69`, opcode at `[7]`;
observed state opcodes `0xA9`/`0xAA`) and are AES-encrypted to `rwChar`. Full builder set
in `libskytone-jni.so`:

```
State/light : setState setStateWithFilter setDefaultState setDefaultStateWithFilter
              setDynamic setRainbow setGradient setFlickerState setSpecialEffects
              setFindme setDefindMosquito setUdimmerOnOff setUdimmerRollback
Groups      : setGRP getGRP setGrpList isValidGroup
Switch/relay: setRelayState setWallSwitchBr setStateCurtain setMaxValueCurtain
Timers/alarm: setTimer setTimerWithFlick setTimerWithGradual setTimerWithTriggle
              getAlarmData alarmData alarm2json setUTC getUTC getTimeZone
Status/meta : getState OnlineStateParse getFwVer getLastCmdRst
              electricityConsumption* reboot
Reset/keys  : RfReset RfReset_result resetAll setKey(setCurCommunity*)
Crypto      : encryption_data decryption_data
```

---

## 7. How these notes were obtained (reproducibility)

The app ships 32-bit-ARM-only libs (`lib/armeabi`, no arm64) → can't run on Apple-silicon
emulators (`INSTALL_FAILED_NO_MATCHING_ABIS`). Run instead in **redroid** (containerised
Android, no hypervisor) on an Ampere ARM host with 32-bit EL0 support.

1. **Static:** `jadx` on `classes.dex` (`com.ledosmart.*`); `arm-linux-gnueabi-objdump
   -M force-thumb` on `libskytone-jni.so` for reset builders + `manu_elem`.
2. **Assets:** AppCan "3G2WIN Safe Guard" encrypts every HTML/JS asset (incl.
   `reset.html`) with native RC4 keyed by MD5(appkey + 255-byte salt) (`nativeHtmlDecode`
   in `libappcan.so`). Instead of reimplementing it, the running app's WebView is
   debuggable: `adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>`, then
   Chrome DevTools Protocol with `suppress_origin`, navigate to
   `content://com.skytone.LedoBle.sp/android_asset/widget/<file>` and read the
   already-decrypted DOM.
3. **Cross-check:** on-air layout confirmed against this repo's `protocol.py` (port of
   `mjg59/python-tikteck`).

No BLE radio exists in the container, so commands were recovered from code, not captured
on-air.

---

## 8. Open questions / next steps

**Answered this session:** default creds (`Smart Light`/`123`); why software reset needs
the password; that RF reset does **not** (unauthenticated write to `1921`/`1920` in the
power-on window); firmware version is passively readable (`manu[10]>>2`); factory-reset
opcode `0xFC`; the full GATT + command map.

**Still open — validate before relying on in production:**
- [ ] **Capture an HCI snoop log** from a phone running the real app during (a) an RF
  reset and (b) a factory reset, and diff against §4.1/§4.2 byte-for-byte. This is the
  one thing not verified on-air.
- [ ] Confirm the exact length of the RF-reset power-on window per firmware (doc says
  "~1 min"; may differ) and whether `slCmdChar` must be written with/without response.
- [ ] Confirm whether firmware `< 24` exposes service `1920` at all (if not, those bulbs
  are power-cycle-only and an RF-reset button should be hidden for them).
- [ ] Decode the `setKey` frame (opcode + payload) so an integration could *re-key* a
  bulb (change its password) rather than only reset it.
- [ ] Map control opcodes precisely (`setState`/`setDynamic`/`setGradient` params) if
  effects/scenes/timers are ever added here.
- [ ] Verify `getState` / `OnlineStateParse` so the integration could drop `assumed_state`
  and report real on/off + colour.
