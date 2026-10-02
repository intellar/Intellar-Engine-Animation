"""Shared building blocks of the Intellar-Engine-Animation chain.

This module is the **Python twin** of the C++ runtime (`src/Iska/*.cpp`): same
binary format, same blit maths, same transparency colour. The Python tools
(`iska_pack`, `iska_preview`, `iska_clip_check`) and the runtime can therefore
check each other.

ISKA v1 format (little-endian, everything in screen pixels):

  header 32 B : "ISKA", u16 version, u16 headerBytes, u16 stageW, u16 stageH,
                u16 boneCount, u16 partCount, u16 animCount, u16 reserved,
                u32 pixelBytes, u32 pixelCount, u32 pixelCrc32
  bones  : boneCount x 12 B : i16 parent(-1 = root), i16 restX, i16 restY,
                              i16 restAngle(tenths of a degree), u32 reserved
  parts  : partCount x 26 B : i16 bone(-1 = none), i16 pivotX, i16 pivotY,
                              u16 spriteW, u16 spriteH, u16 drawOrder,
                              u16 flags, u16 reserved, u16 reserved2,
                              u32 pixelOffset(bytes), u32 pixelBytes
                              -- the sprite box is contiguous inside the pixel
                              block (pixelOffset = byte of the top-left corner)
  anims  : animCount x { u16 nameLen, UTF-8 name, u16 flags(1 = loop),
                         u16 keyCount, u32 durationMs,
                         keyCount x { u16 tMs,
                                      boneCount x (i16 dx, i16 dy, i16 rot,
                                                   i16 sx, i16 sy) } }
  pixels : RGB565 block of the sprite boxes, concatenated (offset and size per
           part).

Transparency: a **magenta** pixel (RGB565 0xF81F) is never written. The packer
therefore turns the translucent pixels of the PNG into magenta; avoiding pure
magenta in the artwork is up to the artist.

Transformations (identical on the C++ side): every bone carries a part and
defines a joint. For a bone:

    world_position = parent_position + R(parent_angle) * (parent_scale (.) local_rest)
    world_angle    = parent_angle + local_angle
    world_scale    = local_scale              <- NOT inherited, on purpose

The local scale is not inherited: shrinking the torso does not deform the head,
it only pulls it down (handy for squash and stretch). The scale is applied only
to the part drawn by the bone.

A part is drawn like this (P = pivot inside the sprite box, J = joint):

    forward : dst = J + R(angle) * (S * (p - P))
    inverse : p   = P + S^-1 * R(-angle) * (dst - J)

The angle is in degrees, **positive = clockwise** on screen (y axis downwards),
0 = sprite not rotated.
"""
from __future__ import annotations

import array
import math
import struct

MAGIC = b"ISKA"
VERSION = 1
HEADER_BYTES = 32
BONE_BYTES = 12
PART_BYTES = 26
ANIM_FLAG_LOOP = 1

ANGLE_SCALE = 10.0        # angles stored in tenths of a degree
FIXED_SCALE = 10000.0     # scales stored in 1/10000 (10000 = x1)
MAGENTA_565 = 0xF81F      # transparency key
MAX_U16 = 0xFFFF

POS_LIMIT = 32767.0


def round_i16(value: float) -> int:
    """Rounded, clamped to the i16 range (the format fields are i16)."""
    return max(-POS_LIMIT, min(POS_LIMIT, int(round(value))))


def rgb_to_565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def rgb565_to_rgb(value: int):
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def new_frame(width: int, height: int, color: int = 0x0000):
    """RGB565 framebuffer (array('H'), row by row)."""
    return array.array("H", [color]) * (width * height)


class Skeleton:
    """Runtime rig: bones + parts, and resolution of a pose into screen placements.

    Bones must be ordered **parents before children** (invariant of the format).
    A pose is a list of tuples `(dx, dy, dRot, sx, sy)` per bone, as deltas from
    the rest pose.
    """

    def __init__(self, rig: dict):
        self.stage_w = rig["stage"]["w"]
        self.stage_h = rig["stage"]["h"]
        self.bones = rig["bones"]
        self.parts = sorted(rig["parts"], key=lambda p: p["draw_order"])
        self.index = {b["name"]: i for i, b in enumerate(self.bones)}

    def rest_pose(self):
        return [(0.0, 0.0, 0.0, 1.0, 1.0) for _ in self.bones]

    def named_pose(self, values: dict):
        """Pose from a `{bone: {dx, dy, rot, sx, sy}}` dict (defaults = rest)."""
        pose = self.rest_pose()
        for name, delta in values.items():
            i = self.index.get(name)
            if i is None:
                raise KeyError(f"unknown bone in pose: {name}")
            pose[i] = (float(delta.get("dx", 0.0)), float(delta.get("dy", 0.0)),
                       float(delta.get("rot", 0.0)), float(delta.get("sx", 1.0)),
                       float(delta.get("sy", 1.0)))
        return pose

    def resolve_bones(self, pose):
        """[(x, y, world_angle, (sx, sy))] per bone, in rig order."""
        world = []
        for i, bone in enumerate(self.bones):
            dx, dy, drot, sx, sy = pose[i]
            local_x = bone["rest"][0] + dx
            local_y = bone["rest"][1] + dy
            local_angle = bone["angle"] + drot
            parent = bone["parent"]
            if parent is None:
                world.append((float(local_x), float(local_y), local_angle, (sx, sy)))
                continue
            pj_x, pj_y, p_angle, p_scale = world[self.index[parent]]
            ux, uy = local_x * p_scale[0], local_y * p_scale[1]
            a = math.radians(p_angle)
            cos_a, sin_a = math.cos(a), math.sin(a)
            world.append((pj_x + ux * cos_a - uy * sin_a,
                          pj_y + ux * sin_a + uy * cos_a,
                          p_angle + local_angle,
                          # scale deliberately NOT inherited (see module docstring)
                          (sx, sy)))
        return world

    def resolve(self, pose):
        """[(part, (jx, jy), world_angle, (sx, sy))] ready to be blitted."""
        world = self.resolve_bones(pose)
        return [(part, world[self.index[part["bone"]]][:2],
                 world[self.index[part["bone"]]][2],
                 world[self.index[part["bone"]]][3]) for part in self.parts]

    def draw(self, buf, pose, sprites):
        """Draws every part (draw order) into an RGB565 framebuffer.

        `sprites[part_name] = (array('H'), width, height)`.
        """
        for part, joint, angle, scale in self.resolve(pose):
            pixels, sw, sh = sprites[part["name"]]
            blit_part(buf, self.stage_w, self.stage_h, pixels, sw, sh,
                      part["pivot"], joint, angle, scale)


def image_to_sprite(img, size, alpha_threshold: int = 128):
    """PNG (Pillow) -> array('H') RGB565, scaled, magenta background.

    This is exactly what `iska_pack.py` does before writing the pixel block.
    """
    rgba = img.convert("RGBA").resize(size, __import__("PIL.Image", fromlist=["Image"]).LANCZOS)
    width, height = rgba.size
    src = rgba.load()
    out = array.array("H", bytes(width * height * 2))
    for y in range(height):
        row = y * width
        for x in range(width):
            r, g, b, a = src[x, y]
            out[row + x] = MAGENTA_565 if a < alpha_threshold else rgb_to_565(r, g, b)
    return out


def frame_to_png(buf, width: int, height: int, path: str, scale: int = 1) -> None:
    """RGB565 framebuffer -> PNG (preview / diff)."""
    from PIL import Image
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        row = y * width
        for x in range(width):
            px[x, y] = rgb565_to_rgb(buf[row + x])
    if scale > 1:
        img = img.resize((width * scale, height * scale), Image.NEAREST)
    img.save(path)

def blit_part(dst, dst_w: int, dst_h: int, pixels, sprite_w: int, sprite_h: int,
              pivot, joint, angle_deg: float, scale=(1.0, 1.0), key: bool = True) -> None:
    """Draws a sprite box rotated around its pivot, with colour keying.

    `dst`: RGB565 framebuffer; `pixels`: array('H') of sprite_w*sprite_h;
    `pivot`/`joint`: (x, y) pairs; `angle_deg`: clockwise; `scale`: (sx, sy).
    Magenta pixels (and, if `key` is set, transparent ones) are skipped.
    """
    if sprite_w <= 0 or sprite_h <= 0 or not pixels:
        return
    sx_scale = scale[0] if abs(scale[0]) > 1e-6 else 1e-6
    sy_scale = scale[1] if abs(scale[1]) > 1e-6 else 1e-6
    a = math.radians(angle_deg)
    cos_a, sin_a = math.cos(a), math.sin(a)
    px, py = pivot
    jx, jy = joint

    # bounding box of the four corners, after rotation + scaling
    corners = []
    for cx, cy in ((0.0, 0.0), (float(sprite_w), 0.0),
                   (float(sprite_w), float(sprite_h)), (0.0, float(sprite_h))):
        ux, uy = (cx - px) * sx_scale, (cy - py) * sy_scale
        corners.append((jx + ux * cos_a - uy * sin_a, jy + ux * sin_a + uy * cos_a))
    x0 = max(0, int(math.floor(min(c[0] for c in corners))))
    x1 = min(dst_w - 1, int(math.ceil(max(c[0] for c in corners))))
    y0 = max(0, int(math.floor(min(c[1] for c in corners))))
    y1 = min(dst_h - 1, int(math.ceil(max(c[1] for c in corners))))
    if x1 < x0 or y1 < y0:
        return

    inv_sx, inv_sy = 1.0 / sx_scale, 1.0 / sy_scale
    for y in range(y0, y1 + 1):
        dy = (y + 0.5) - jy
        row = y * dst_w
        for x in range(x0, x1 + 1):
            dx = (x + 0.5) - jx
            # R(-a) then the inverse of the scale, then back into the sprite box
            rx = dx * cos_a + dy * sin_a
            ry = -dx * sin_a + dy * cos_a
            u = px + rx * inv_sx
            v = py + ry * inv_sy
            if u < 0.0 or v < 0.0:
                continue
            iu, iv = int(u), int(v)
            if iu >= sprite_w or iv >= sprite_h:
                continue
            value = pixels[iv * sprite_w + iu]
            if value == MAGENTA_565:
                continue
            dst[row + x] = value

# --------------------------------------------------------------------------- #
# Animations
# --------------------------------------------------------------------------- #

def sample_pose(anim: dict, t_ms: float):
    """Pose interpolated linearly at `t_ms` (keys sorted).

    A looping animation is brought back into [0, duration) by the caller; a
    one-shot animation holds its last pose past the end. The five components
    (dx, dy, rot, sx, sy) are interpolated linearly.
    """
    keys = anim["keys"]
    if not keys:
        raise ValueError(f"animation {anim['name']} has no key")
    if t_ms <= keys[0][0]:
        return keys[0][1]
    if t_ms >= keys[-1][0]:
        return keys[-1][1]
    for i in range(1, len(keys)):
        t0, p0 = keys[i - 1]
        t1, p1 = keys[i]
        if t_ms <= t1:
            u = 0.0 if t1 == t0 else (t_ms - t0) / (t1 - t0)
            return [tuple(a + (b - a) * u for a, b in zip(pa, pb))
                    for pa, pb in zip(p0, p1)]
    return keys[-1][1]


def anim_time(anim: dict, elapsed_ms: float) -> float:
    """Instant to sample, taking the loop into account."""
    if anim.get("loop") and anim["duration"] > 0:
        return elapsed_ms % anim["duration"]
    return min(elapsed_ms, anim["duration"])


def carry_keys(skeleton, keys):
    """Full poses `[(t, pose)]` from **sparse** keys.

    Authoring rule (the same in tools/anims_rabbit3.py and iska_pack.py): a bone
    missing from a key keeps the value of the previous key; naming a bone without
    giving a component resets that component to rest. To send a bone back to
    rest, write it explicitly (`"armL": {}`). Raises `KeyError` on an unknown
    bone name.
    """
    out = []
    carried = {}
    for key in keys:
        named = {bone: dict(delta) for bone, delta in carried.items()}
        for bone, delta in (key.get("pose") or {}).items():
            named[bone] = dict(delta)
        out.append((int(round(key["t"])), skeleton.named_pose(named)))
        carried = named
    return out


# --------------------------------------------------------------------------- #
# Binary format
# --------------------------------------------------------------------------- #

def build_iska(stage_w, stage_h, bones, parts, animations, pixels) -> bytes:
    """Assembles an .iska file (see the module docstring).

    `bones`  : [{"parent": index|None, "rest": (x, y), "angle": degrees}]
    `parts`  : [{"bone": index|-1, "pivot": (x, y), "sprite": (w, h),
                 "draw_order": int, "flags": int,
                 "pixel_offset": bytes, "pixel_bytes": bytes}]
    `anims`  : [{"name", "loop", "duration_ms", "keys": [(t_ms, pose)]}]
    `pixels` : array('H') RGB565 (the whole atlas, box by box)
    """
    import zlib

    bone_count = len(bones)
    for i, bone in enumerate(bones):
        parent = bone["parent"]
        if parent is not None and not 0 <= parent < i:
            raise ValueError(f"bone {i}: parent {parent} must come before the child "
                             "(ISKA format invariant)")
    pixel_bytes = array.array("H", pixels).tobytes()

    out = bytearray()
    out += struct.pack("<4sHHHHHHHHIII", MAGIC, VERSION, HEADER_BYTES, stage_w, stage_h,
                       bone_count, len(parts), len(animations), 0,
                       len(pixel_bytes), len(pixels), zlib.crc32(pixel_bytes) & 0xFFFFFFFF)

    for bone in bones:
        parent = -1 if bone["parent"] is None else bone["parent"]
        out += struct.pack("<hhhhi", parent, round_i16(bone["rest"][0]),
                           round_i16(bone["rest"][1]),
                           round_i16(bone["angle"] * ANGLE_SCALE), 0)

    for part in parts:
        out += struct.pack("<hhhHHHHHHII", part["bone"],
                           round_i16(part["pivot"][0]), round_i16(part["pivot"][1]),
                           part["sprite"][0], part["sprite"][1],
                           part["draw_order"], part.get("flags", 0), 0, 0,
                           part["pixel_offset"], part["pixel_bytes"])

    for anim in animations:
        name = anim["name"].encode("utf-8")
        flags = ANIM_FLAG_LOOP if anim.get("loop") else 0
        keys = anim["keys"]
        out += struct.pack("<H", len(name)) + name
        out += struct.pack("<HHI", flags, len(keys), int(round(anim["duration_ms"])))
        for t_ms, pose in keys:
            if len(pose) != bone_count:
                raise ValueError(f"{anim['name']}: pose of {len(pose)} bones, "
                                 f"{bone_count} expected")
            out += struct.pack("<H", round_i16(t_ms))
            for dx, dy, rot, sx, sy in pose:
                out += struct.pack("<hhhhh", round_i16(dx), round_i16(dy),
                                   round_i16(rot * ANGLE_SCALE),
                                   round_i16(sx * FIXED_SCALE),
                                   round_i16(sy * FIXED_SCALE))

    out += pixel_bytes
    return bytes(out)


def parse_iska(blob: bytes) -> dict:
    """Reads back an .iska (used by iska_preview / iska_info / iska_clip_check)."""
    import zlib

    if blob[:4] != MAGIC:
        raise ValueError("this is not an ISKA file")
    (magic, version, header_bytes, stage_w, stage_h, bone_count, part_count,
     anim_count, _reserved, pixel_bytes_len, pixel_count, crc) = struct.unpack_from(
        "<4sHHHHHHHHIII", blob, 0)
    if version != VERSION:
        raise ValueError(f"unsupported ISKA version {version} (tool is at v{VERSION})")
    offset = header_bytes

    bones = []
    for _ in range(bone_count):
        parent, rx, ry, angle, _r = struct.unpack_from("<hhhhi", blob, offset)
        offset += BONE_BYTES
        bones.append({"parent": None if parent < 0 else parent,
                      "rest": [rx, ry], "angle": angle / ANGLE_SCALE})
    parts = []
    for _ in range(part_count):
        (bone, px, py, sw, sh, order, flags, _r1, _r2,
         p_off, p_len) = struct.unpack_from("<hhhHHHHHHII", blob, offset)
        offset += PART_BYTES
        parts.append({"bone": bone, "pivot": [px, py], "sprite": [sw, sh],
                      "draw_order": order, "flags": flags,
                      "pixel_offset": p_off, "pixel_bytes": p_len})
    anims = {}
    for _ in range(anim_count):
        (name_len,) = struct.unpack_from("<H", blob, offset)
        offset += 2
        name = blob[offset:offset + name_len].decode("utf-8")
        offset += name_len
        flags, key_count, duration = struct.unpack_from("<HHI", blob, offset)
        offset += 8
        keys = []
        for _k in range(key_count):
            (t_ms,) = struct.unpack_from("<H", blob, offset)
            offset += 2
            pose = []
            for _b in range(bone_count):
                dx, dy, rot, sx, sy = struct.unpack_from("<hhhhh", blob, offset)
                offset += 10
                pose.append((dx, dy, rot / ANGLE_SCALE, sx / FIXED_SCALE,
                             sy / FIXED_SCALE))
            keys.append((t_ms, pose))
        anims[name] = {"name": name, "loop": bool(flags & ANIM_FLAG_LOOP),
                       "duration": duration, "keys": keys}

    pixels_raw = blob[offset:offset + pixel_bytes_len]
    if zlib.crc32(pixels_raw) & 0xFFFFFFFF != crc:
        raise ValueError("invalid pixel block CRC")
    pixels = array.array("H")
    pixels.frombytes(pixels_raw[:pixel_count * 2])
    return {"version": version, "stage": [stage_w, stage_h], "bones": bones,
            "parts": parts, "anims": anims, "pixels": pixels,
            "pixel_offset": offset, "bytes": len(blob)}


def sprite_view(iska: dict, part: dict):
    """(array('H'), width, height) of a part's box, seen inside the atlas."""
    width, height = part["sprite"]
    base = part["pixel_offset"] // 2
    out = array.array("H", bytes(width * height * 2))
    for y in range(height):
        src = base + y * width
        out[y * width:y * width + width] = iska["pixels"][src:src + width]
    return out, width, height


def skeleton_from_iska(data: dict):
    """A `Skeleton` built straight from an .iska read back.

    Bones and parts have no name in the binary (the runtime works by index): they
    are therefore named `bone0..boneN` / `part0..partN` here, only for the Python
    tooling.
    """
    rig = {
        "stage": {"w": data["stage"][0], "h": data["stage"][1]},
        "bones": [{"name": f"bone{i}",
                   "parent": None if b["parent"] is None else f"bone{b['parent']}",
                   "rest": b["rest"], "angle": b["angle"]}
                  for i, b in enumerate(data["bones"])],
        "parts": [{"name": f"part{i}",
                   "bone": f"bone{p['bone']}" if p["bone"] >= 0 else "bone0",
                   "pivot": p["pivot"], "sprite": p["sprite"],
                   "draw_order": p["draw_order"], "_index": i}
                  for i, p in enumerate(data["parts"])],
    }
    return Skeleton(rig)


def sprites_from_iska(data: dict, skeleton) -> dict:
    """`{part name: (pixels, width, height)}` as expected by `Skeleton.draw`."""
    return {part["name"]: sprite_view(data, data["parts"][part["_index"]])
            for part in skeleton.parts}
