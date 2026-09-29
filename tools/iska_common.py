"""Briques communes a la chaine Intellar-Engine-Animation.

Ce module est le **jumeau Python** du runtime C++ (`src/iska_*.cpp`) : meme
format binaire, meme math de blit, meme couleur de transparence. Les outils
Python (`iska_pack`, `iska_preview`, `iska_clip_check`) et le runtime peuvent
donc se controler l'un l'autre.

Format ISKA v1 (little-endian, tout est en pixels ecran) :

  en-tete 32 o : "ISKA", u16 version, u16 headerBytes, u16 stageW, u16 stageH,
                 u16 boneCount, u16 partCount, u16 animCount, u16 reserved,
                 u32 pixelBytes, u32 pixelCount, u32 pixelCrc32
  os     : boneCount x 12 o : i16 parent(-1 = racine), i16 restX, i16 restY,
                              i16 restAngle(dixiemes de degre), u32 reserved
  parts  : partCount x 26 o : i16 bone(-1 = aucun), i16 pivotX, i16 pivotY,
                              u16 spriteW, u16 spriteH, u16 drawOrder,
                              u16 flags, u16 reserved, u16 reserved2,
                              u32 pixelOffset(octets), u32 pixelBytes
                              -- la case sprite est contigue dans le bloc pixels
                              (pixelOffset = octet du coin haut-gauche)
  anims  : animCount x { u16 nameLen, nom UTF-8, u16 flags(1 = boucle),
                         u16 keyCount, u32 durationMs,
                         keyCount x { u16 tMs,
                                      boneCount x (i16 dx, i16 dy, i16 rot,
                                                   i16 sx, i16 sy) } }
  pixels : bloc RGB565 des cases sprite, concatenees (pixelOffset/pixelBytes).

Transparence : un pixel **magenta** (RGB565 0xF81F) n'est jamais ecrit. Le
packer transforme donc les pixels translucides du PNG en magenta ; c'est a
l'artiste d'eviter de peindre du magenta pur.

Transformations (identiques cote C++) : chaque os porte une part et definit une
articulation. Pour un os :

    position_monde = position_parent + R(angle_parent) * (echelle_parent (.) rest_local)
    angle_monde    = angle_parent + angle_local
    echelle_monde  = echelle_locale            <- NON heritee, volontairement

L'echelle locale n'est pas heritee : reduire le torse ne deforme pas la tete, il
la fait seulement descendre (utile pour un squash and stretch). L'echelle n'est
appliquee qu'a la part dessinee par l'os.

Une part est dessinee ainsi (P = pivot dans la case sprite, J = articulation) :

    avant : dst = J + R(angle) * (S * (p - P))
    arriere : p  = P + S^-1 * R(-angle) * (dst - J)

L'angle est en degres, **positif = horaire** a l'ecran (repere y vers le bas),
0 = sprite non tourne.
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

ANGLE_SCALE = 10.0        # angles stockes en dixiemes de degre
FIXED_SCALE = 10000.0     # echelles stockees en 1/10000 (10000 = x1)
MAGENTA_565 = 0xF81F      # cle de transparence
MAX_U16 = 0xFFFF

POS_LIMIT = 32767.0


def round_i16(value: float) -> int:
    """Arrondi borne a l'intervalle i16 (les champs du format sont en i16)."""
    return max(-POS_LIMIT, min(POS_LIMIT, int(round(value))))


def rgb_to_565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def rgb565_to_rgb(value: int):
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def new_frame(width: int, height: int, color: int = 0x0000):
    """Framebuffer RGB565 (array('H'), ligne par ligne)."""
    return array.array("H", [color]) * (width * height)


class Skeleton:
    """Rig runtime : os + parts, et resolution d'une pose en placements ecran.

    Les os doivent etre ordonnes **parents avant enfants** (invariant du format).
    Une pose est une liste de tuples `(dx, dy, dRot, sx, sy)` par os, en deltas
    par rapport au repos.
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
        """Pose depuis un dict `{os: {dx, dy, rot, sx, sy}}` (defauts = repos)."""
        pose = self.rest_pose()
        for name, delta in values.items():
            i = self.index.get(name)
            if i is None:
                raise KeyError(f"os inconnu dans la pose : {name}")
            pose[i] = (float(delta.get("dx", 0.0)), float(delta.get("dy", 0.0)),
                       float(delta.get("rot", 0.0)), float(delta.get("sx", 1.0)),
                       float(delta.get("sy", 1.0)))
        return pose

    def resolve_bones(self, pose):
        """[(x, y, angle_monde, (sx, sy))] par os, dans l'ordre du rig."""
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
                          # echelle volontairement NON heritee (voir docstring module)
                          (sx, sy)))
        return world

    def resolve(self, pose):
        """[(part, (jx, jy), angle_monde, (sx, sy))] pret a etre blitte."""
        world = self.resolve_bones(pose)
        return [(part, world[self.index[part["bone"]]][:2],
                 world[self.index[part["bone"]]][2],
                 world[self.index[part["bone"]]][3]) for part in self.parts]

    def draw(self, buf, pose, sprites):
        """Dessine toutes les parts (ordre de dessin) dans un framebuffer RGB565.

        `sprites[part_name] = (array('H'), largeur, hauteur)`.
        """
        for part, joint, angle, scale in self.resolve(pose):
            pixels, sw, sh = sprites[part["name"]]
            blit_part(buf, self.stage_w, self.stage_h, pixels, sw, sh,
                      part["pivot"], joint, angle, scale)


def image_to_sprite(img, size, alpha_threshold: int = 128):
    """PNG (Pillow) -> array('H') RGB565 mis a l'echelle, fond magenta.

    C'est exactement ce que fait `iska_pack.py` avant d'ecrire le bloc pixels.
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
    """Framebuffer RGB565 -> PNG (apercu / diff)."""
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
    """Dessine une case sprite tournee autour de son pivot, avec cle de couleur.

    `dst` : framebuffer RGB565 ; `pixels` : array('H') de sprite_w*sprite_h ;
    `pivot`/`joint` : couples (x, y) ; `angle_deg` : horaire ; `scale` : (sx, sy).
    Les pixels magenta (et, si `key`, transparents) sont sautes.
    """
    if sprite_w <= 0 or sprite_h <= 0 or not pixels:
        return
    sx_scale = scale[0] if abs(scale[0]) > 1e-6 else 1e-6
    sy_scale = scale[1] if abs(scale[1]) > 1e-6 else 1e-6
    a = math.radians(angle_deg)
    cos_a, sin_a = math.cos(a), math.sin(a)
    px, py = pivot
    jx, jy = joint

    # boite englobante des quatre coins, apres rotation + echelle
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
            # R(-a) puis inverse de l'echelle, puis retour au repere case sprite
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
    """Pose interpolee lineairement a `t_ms` (cles triees).

    Une animation en boucle est ramenee dans [0, duration) par l'appelant ; une
    animation one-shot tient sa derniere pose au dela de la fin. Les cinq
    composantes (dx, dy, rot, sx, sy) sont interpolees lineairement.
    """
    keys = anim["keys"]
    if not keys:
        raise ValueError(f"animation {anim['name']} sans cle")
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
    """Instant a echantillonner, en tenant compte de la boucle."""
    if anim.get("loop") and anim["duration"] > 0:
        return elapsed_ms % anim["duration"]
    return min(elapsed_ms, anim["duration"])


def carry_keys(skeleton, keys):
    """Poses completes `[(t, pose)]` a partir de cles **sparses**.

    Regle d'authoring (la meme dans tools/anims_rabbit3.py et iska_pack.py) : un
    os absent d'une cle conserve la valeur de la cle precedente ; citer un os sans
    preciser une composante remet cette composante au repos. Pour renvoyer un os au
    repos, on l'ecrit donc explicitement (`"armL": {}`). Leve `KeyError` sur un
    nom d'os inconnu.
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
# Format binaire
# --------------------------------------------------------------------------- #

def build_iska(stage_w, stage_h, bones, parts, animations, pixels) -> bytes:
    """Assemble un fichier .iska (voir la docstring du module).

    `bones`  : [{"parent": index|None, "rest": (x, y), "angle": degres}]
    `parts`  : [{"bone": index|-1, "pivot": (x, y), "sprite": (w, h),
                 "draw_order": int, "flags": int,
                 "pixel_offset": octets, "pixel_bytes": octets}]
    `anims`  : [{"name", "loop", "duration_ms", "keys": [(t_ms, pose)]}]
    `pixels` : array('H') RGB565 (tout l'atlas, case par case)
    """
    import zlib

    bone_count = len(bones)
    for i, bone in enumerate(bones):
        parent = bone["parent"]
        if parent is not None and not 0 <= parent < i:
            raise ValueError(f"os {i} : le parent {parent} doit preceder l'enfant "
                             "(invariant du format ISKA)")
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
                raise ValueError(f"{anim['name']} : pose de {len(pose)} os, "
                                 f"{bone_count} attendus")
            out += struct.pack("<H", round_i16(t_ms))
            for dx, dy, rot, sx, sy in pose:
                out += struct.pack("<hhhhh", round_i16(dx), round_i16(dy),
                                   round_i16(rot * ANGLE_SCALE),
                                   round_i16(sx * FIXED_SCALE),
                                   round_i16(sy * FIXED_SCALE))

    out += pixel_bytes
    return bytes(out)


def parse_iska(blob: bytes) -> dict:
    """Relit un .iska (utilise par iska_preview / iska_info / iska_clip_check)."""
    import zlib

    if blob[:4] != MAGIC:
        raise ValueError("ce n'est pas un fichier ISKA")
    (magic, version, header_bytes, stage_w, stage_h, bone_count, part_count,
     anim_count, _reserved, pixel_bytes_len, pixel_count, crc) = struct.unpack_from(
        "<4sHHHHHHHHIII", blob, 0)
    if version != VERSION:
        raise ValueError(f"version ISKA {version} non geree (outil en v{VERSION})")
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
        raise ValueError("CRC du bloc de pixels invalide")
    pixels = array.array("H")
    pixels.frombytes(pixels_raw[:pixel_count * 2])
    return {"version": version, "stage": [stage_w, stage_h], "bones": bones,
            "parts": parts, "anims": anims, "pixels": pixels,
            "pixel_offset": offset, "bytes": len(blob)}


def sprite_view(iska: dict, part: dict):
    """(array('H'), largeur, hauteur) de la case d'une part, vue dans l'atlas."""
    width, height = part["sprite"]
    base = part["pixel_offset"] // 2
    out = array.array("H", bytes(width * height * 2))
    for y in range(height):
        src = base + y * width
        out[y * width:y * width + width] = iska["pixels"][src:src + width]
    return out, width, height


def skeleton_from_iska(data: dict):
    """`Skeleton` construit directement depuis un .iska relu.

    Les os et parts n'ont pas de nom dans le binaire (le moteur travaille par
    index) : ils sont donc nommes `os0..osN` / `part0..partN` ici, uniquement
    pour l'outillage Python.
    """
    rig = {
        "stage": {"w": data["stage"][0], "h": data["stage"][1]},
        "bones": [{"name": f"os{i}",
                   "parent": None if b["parent"] is None else f"os{b['parent']}",
                   "rest": b["rest"], "angle": b["angle"]}
                  for i, b in enumerate(data["bones"])],
        "parts": [{"name": f"part{i}",
                   "bone": f"os{p['bone']}" if p["bone"] >= 0 else "os0",
                   "pivot": p["pivot"], "sprite": p["sprite"],
                   "draw_order": p["draw_order"], "_index": i}
                  for i, p in enumerate(data["parts"])],
    }
    return Skeleton(rig)


def sprites_from_iska(data: dict, skeleton) -> dict:
    """`{nom de part: (pixels, largeur, hauteur)}` attendu par `Skeleton.draw`."""
    return {part["name"]: sprite_view(data, data["parts"][part["_index"]])
            for part in skeleton.parts}

