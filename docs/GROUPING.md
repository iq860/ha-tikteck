# Grouping and ungrouping Tikteck bulbs

**Short version:** each bulb is its own light by default. To control several together, make
a Home Assistant **Light group**. You don’t need to understand any of the “why” below to do
that — jump to [Group several lamps](#group-several-lamps).

---

## Why this needs explaining

Tikteck/Telink bulbs form a **mesh**: every bulb that shares the same mesh name
(`Smart Light`) and password (`123`) is on one network. Historically, a command sent to one
bulb was *broadcast* to the whole mesh — so changing one lamp changed them all, and Home
Assistant only knew about the one you touched.

This integration fixes that by addressing each command to a **single bulb** (its own mesh
“node address”). So out of the box:

- **One entity = one physical bulb.** Toggle a lamp and only that lamp reacts.
- Grouping is done the normal Home Assistant way, with a **Light group** — not inside this
  integration.

You normally never touch mesh addresses. They’re there for the two uncommon cases below.

---

## Group several lamps

Use a built-in Home Assistant **Light group**. It makes one light that controls all the
bulbs you put in it; the individual lamps still work on their own too.

1. **Settings → Devices & services → Helpers** tab.
2. **+ Create helper → Light group**.
3. Give it a name (e.g. *Living room lamps*).
4. Pick the Tikteck lights you want in the group.
5. **Create**.

You now have a single light (e.g. `light.living_room_lamps`). Turn it on/off or set a colour
and all the bulbs in it follow. Put it on a dashboard, in automations, or in a voice
assistant like any other light.

> Tip: a bulb can be in more than one group (e.g. *Living room* and *Whole house*).

## Ungroup

- **Remove one lamp from a group:** Helpers → open the group → edit its members → remove the
  lamp → save.
- **Delete a group entirely:** Helpers → open the group → delete. The individual bulbs are
  untouched and keep working on their own.

Un-grouping never changes the bulbs themselves — a Light group is just a convenience light
layered on top.

---

## Advanced: the “Mesh address” option

Each bulb’s integration **options** (the gear icon on the bulb’s entry in
*Devices & services → Tikteck*) has a **Mesh address** field. You almost never need it.

| You enter | What happens |
|---|---|
| *(blank)* | **Default.** This entity controls **only this bulb** (its own node address, found automatically). |
| `all` | This entity controls **every bulb on the mesh** at once (the old broadcast behaviour). |
| e.g. `0x0097` | This entity targets one specific bulb by its node address (hex). For fixing the rare case below. |

### When would I use `all`?

Only if you specifically want *one* Home Assistant light to drive *all* your Tikteck bulbs
together and don’t want a Light group. A Light group ([above](#group-several-lamps)) is the
better choice almost always, because Home Assistant then tracks each bulb separately.

### A lamp stopped responding after updating

The automatic per-bulb address is correct for virtually all bulbs, but a bulb with an unusual
mesh address could end up targeted wrongly. If one lamp goes unresponsive:

1. Open that bulb’s **options** (gear icon).
2. Set **Mesh address** to `all` and **Submit** — it’ll respond again (it just also drives
   the mesh now).
3. Or, if you know the bulb’s real node address, enter it in hex (e.g. `0x0097`) to keep it
   independent.

The node address is listed on the bulb’s **Firmware version** sensor (attribute
`mesh_node_address`) whenever a direct Bluetooth adapter can read the bulb — see
[PROTOCOL.md §5](PROTOCOL.md).

---

## In one picture

```
Physical mesh (all share name "Smart Light" / pw 123)
┌─────────────────────────────────────────────┐
│  Bulb A        Bulb B        Bulb C          │
└─────────────────────────────────────────────┘
        ▲             ▲             ▲
        │ node addr   │ node addr   │ node addr      ← default: one entity each
   light.bulb_a  light.bulb_b  light.bulb_c

   light.living_room  ───────────────────────────►  Home Assistant Light group
   (controls A + B together, A and B still work alone)

   an entity set to "all" ──────────────────────►  commands every bulb at once
```
