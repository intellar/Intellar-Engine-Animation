# ISKA format v1

An `.iska` file is **self-contained**: skeleton, RGB565 sprite boxes and
animations. The engine needs nothing else to animate a character -- no Blender,
no PNG, no JSON parser.

Two implementations exist, deliberately identical:

* `src/Iska/` -- C++17, no dependency (the SDL screen is optional);
* `tools/iska_common.py` -- Python, used by the packer and the checking tools.
  `tools/iska_clip_check.py` compares the two renders **pixel for pixel**
  (94 identical frames over the two animations of `rabbit3`).

## Conventions

* **Little-endian** everywhere, unsigned fields unless marked `i`.
* Coordinates in **screen pixels**: X to the right, Y **downwards**.
* Angles in **tenths of a degree**, **positive = clockwise** on screen, `0` =
  sprite not rotated.
* A **magenta** pixel (`RGB565 = 0xF81F`) is the **transparency key**: it is never
  written. The packer turns pixels with alpha < `--alpha-threshold` (128 by
  default) into magenta.

## Header (32 bytes)

| Byte | Type | Field |
| ---: | :--- | :--- |
| 0 | `char[4]` | `"ISKA"` |
| 4 | `u16` | version (1) |
| 6 | `u16` | header size (32) |
| 8 | `u16` | `stageW` (e.g. 240) |
| 10 | `u16` | `stageH` (e.g. 320) |
| 12 | `u16` | bone count |
| 14 | `u16` | part count |
| 16 | `u16` | animation count |
| 18 | `u16` | reserved (0) |
| 20 | `u32` | pixel block size, in bytes |
| 24 | `u32` | RGB565 pixel count |
| 28 | `u32` | CRC32 (IEEE, the one from zlib) of the pixel block |

The CRC makes it possible to detect a truncated or hand-edited asset: the loader
rejects the file when the fingerprint does not match.

## Bones -- 12 bytes per bone

| Offset | Type | Field |
| ---: | :--- | :--- |
| 0 | `i16` | parent index (`-1` = root) |
| 2 | `i16` | `restX` relative **to the parent's head** |
| 4 | `i16` | `restY` |
| 6 | `i16` | rest angle (tenths of a degree) |
| 8 | `u32` | reserved |

**Invariant**: a bone may only reference a parent with a **strictly smaller**
index. The engine therefore resolves the hierarchy in a single pass, and the
packer refuses a rig that does not follow that order.

`rest` is relative to the parent's head (not its tail): every bone is a
**pivot**, and a child follows its parent's pivot.

## Parts -- 26 bytes per part

| Offset | Type | Field |
| ---: | :--- | :--- |
| 0 | `i16` | bone carrying the part (`-1` = none) |
| 2 | `i16` | `pivotX` in the sprite box |
| 4 | `i16` | `pivotY` |
| 6 | `u16` | `spriteW` |
| 8 | `u16` | `spriteH` |
| 10 | `u16` | draw order (increasing: 0 = behind) |
| 12 | `u16` | flags (reserved, 0) |
| 14 | `u16` | reserved |
| 16 | `u16` | reserved |
| 18 | `u32` | `pixelOffset` (byte of the top-left corner in the block) |
| 22 | `u32` | `pixelBytes` (size of the box) |

The boxes are stored **contiguously** (rows follow each other, width =
`spriteW`): the engine has no stride to compute, it points straight into the
block. Parts are written in draw order, from the back to the front.

## Animations

Each animation starts with:

| Type | Field |
| :--- | :--- |
| `u16` | name length (bytes) |
| `char[]` | name in UTF-8, without terminating zero |
| `u16` | flags: bit 0 = **loop** |
| `u16` | key count |
| `u32` | duration in milliseconds |

Then, for each key:

| Type | Field |
| :--- | :--- |
| `u16` | `tMs` (increasing) |
| `i16 x 5` | pose of bone 0: `dx, dy, rot, sx, sy` |
| ... | ... one pose per bone, in skeleton order |

Every key carries **all** the poses (no compression): the engine looks for the
interval `[k0, k1]` and interpolates the five components linearly --
`dx`/`dy` in pixels, `rot` in tenths of a degree, `sx`/`sy` in 1/10000
(`10000` = x1). Reading a key: `O(nb bones)` per frame, no allocation.

Playback rules:

* **looping** animation: `t = elapsed_time mod duration`, and `t = duration` must
  give back exactly the pose of `t = 0` (checked by `iska_clip_check.py`);
* **one-shot** animation: past the duration, the last pose is held; the host can
  test `Player::finished()` to chain the next one.

## Poses and transformations

A pose given by the host is a **delta relative to the rest** of the rig:

```
local_x = restX + dx        local_angle = rest_angle + rot
local_y = restY + dy        local_scale = (sx, sy)
```

Hierarchy resolution, for each bone (parents first):

```
position(bone) = position(parent) + R(angle(parent)) . (scale(parent) * (local_x, local_y))
angle(bone)    = angle(parent) + local_angle
scale(bone)    = local_scale                        <- NOT inherited
```

The scale is **not inherited**: shrinking the torso does not deform the head, it
only makes it go down (useful for *squash and stretch*), and a scale only affects
the part drawn by the bone carrying it. A deliberate choice -- both
implementations do exactly the same.

Drawing a part (`P` = pivot in the box, `J` = joint of its bone):

```
forward : dst = J + R(angle) . (S . (p - P))
inverse : p   = P + S^-1 . R(-angle) . (dst - J)      <- what the blitter does
```

The blitter walks the bounding box of the four rotated corners, applies the
inverse formula for every pixel centre, and samples **nearest neighbour**. A
magenta pixel is never written, so the edges stay sharp (no blending) -- which is
what we want for pixel art on an RGB565 screen.

## Writing animations (JSON -> binary)

Animations are written in JSON (`tools/animations/*.json`) then packed. Two rules
make hand-writing bearable:

1. **A bone absent from a key = value of the previous key** ("sparse channel",
   like Blender channels). A bone that does not move is not written.
2. **A bone cited = its unspecified components go back to rest.** To send a bone
   back to rest, it is therefore written explicitly: `"armL": {}`.

The rule is applied in a single place (`iska_common.carry_keys`), used both by the
animation generator and by the packer.

## Example asset

`assets/rabbit3.iska` (60 kB):

| | |
| :--- | :--- |
| Panel | 240 x 320 |
| Bones | 11 (`root`, `torso`, `head`, `earL/R`, `eyeL/R`, `armL/R`, `footL/R`) |
| Parts | 10 (one per bone except `root`) |
| Animations | `idle_loop` (2400 ms, loop, 28 keys) -- `peek` (2700 ms, one-shot, 20 keys) |
| Pixel block | 55,486 bytes (10 RGB565 boxes) |
| Total | 61,319 bytes |

## Compatibility / evolution

* The header `version` field makes it possible to introduce a v2 format without
  ambiguity: `Iska::parseAsset` rejects any version it does not know, with an
  explicit message, rather than reading it wrong.
* The `reserved` fields, `flags` and bit 1+ of the animation flags are free: that
  is where a sprite mirror (`FLIP_X`) or a per-key non-linear interpolation would
  go.
* Bone and part names **are not stored**: the engine works with indices. The
  Python tooling gives them internal names (`os0`, `part0`) when it reads a binary
  back, and relies on the JSON files for the real names.
