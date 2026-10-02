"""Computes the engine rig (screen coordinates, in pixels) from the Blender export.

    python tools/rig_build.py build/rabbit3/scene.json --id rabbit3 \
        --out tools/rigs/rabbit3.json [--preview build/rabbit3/rig_preview.png]

Input : `build/rabbit3/scene.json` (tools/blender_export.py) -- planes placed in
         Blender + armature.
Output: `tools/rigs/rabbit3.json` -- **runtime rig**: everything is converted to
         screen pixels of the panel (240x320), ready to be packed into an .iska.

Conventions
-----------
* Blender: X to the right, Y upwards, Z towards the screen (larger = in front).
* Engine : X to the right, Y downwards, angle in degrees **clockwise** (0 = upright
  sprite). The conversion therefore flips Y (`stage_y = origin_y - wy * ppu`) and
  the angle (`angle = -rot_z`).

What the script derives, with no manual intervention:

1. **Scale** (`ppu`, pixels per Blender unit): the whole character (all of its
   parts, rotations included) measures `--height-frac` of the panel height
   (0.64 -> 205 px out of 320).
2. **Placement**: the feet line is set at `--feet-y` px, the character is centred
   on the panel axis (`--center bbox|torso|feet|<units>`).
3. **Per part**: sprite box size (rounded), **pivot** (= bone head brought back
   into the plane's image), rest angle, draw order (Blender Z).
4. **Per bone**: parent, rest position relative to the parent, rest angle.

`--angles plane` (default): the rest angle comes from the plane's rotation in
Blender, so the render matches the original placement exactly.
`--angles bone`: the angle comes from the bone direction (head -> tail); useful if
you straightened the bones to define the reference pose.

The resulting rig stays hand-editable: this is what `iska_pack.py` reads.
"""
from __future__ import annotations

import argparse
import json
import math
import os

from PIL import Image, ImageDraw

import iska_common as iska


# --------------------------------------------------------------------------- #
# 2D maths (in the export, the Blender matrices are matrix[row][column])
# --------------------------------------------------------------------------- #

def mat22(matrix):
    return (matrix[0][0], matrix[0][1], matrix[1][0], matrix[1][1])


def translation(matrix):
    return (matrix[0][3], matrix[1][3])


def apply(m, v):
    return (m[0] * v[0] + m[1] * v[1], m[2] * v[0] + m[3] * v[1])


def invert(m):
    det = m[0] * m[3] - m[1] * m[2]
    if abs(det) < 1e-12:
        raise ValueError("plane matrix is not invertible (zero scale?)")
    return (m[3] / det, -m[1] / det, -m[2] / det, m[0] / det)


def world_to_local(part, point):
    """World point -> plane frame (local box, before rotation/scale)."""
    return apply(invert(mat22(part["matrix"])),
                 (point[0] - translation(part["matrix"])[0],
                  point[1] - translation(part["matrix"])[1]))


def part_size_units(part):
    """Plane size in Blender units (local box x plane scale)."""
    local = part["local"]
    m = mat22(part["matrix"])
    return ((local[2] - local[0]) * math.hypot(m[0], m[2]),
            (local[3] - local[1]) * math.hypot(m[1], m[3]))


# --------------------------------------------------------------------------- #

def order_bones(bones_in):
    """Bones with the parents **before** the children (ISKA format invariant)."""
    by_name = {b["name"]: b for b in bones_in}
    ordered = []
    seen = set()

    def visit(bone, chain=()):
        if bone["name"] in seen:
            return
        if bone["name"] in chain:
            raise SystemExit(f"bone cycle around {bone['name']}")
        parent = bone.get("parent")
        if parent:
            if parent not in by_name:
                raise SystemExit(f"bone {bone['name']}: unknown parent {parent}")
            visit(by_name[parent], chain + (bone["name"],))
        seen.add(bone["name"])
        ordered.append(bone)

    for bone in bones_in:
        visit(bone)
    return ordered


def build(scene: dict, args) -> dict:
    parts_in = scene["parts"]
    bones_in = order_bones((scene.get("armature") or {}).get("bones") or [])
    if not bones_in:
        raise SystemExit("scene.json contains no armature: run "
                         "tools/blender_make_rig.py first, or place the armature in Blender.")

    # 1. scale: real height of the character (world boxes, rotations included)
    ys = [v for p in parts_in for v in (p["world_bbox"][1], p["world_bbox"][3])]
    xs = [v for p in parts_in for v in (p["world_bbox"][0], p["world_bbox"][2])]
    units_h = max(ys) - min(ys)
    stage_w, stage_h = args.stage_w, args.stage_h
    ppu = (args.height_frac * stage_h) / units_h

    # 2. placement: feet line + centring
    torso = next((p for p in parts_in if p["name"].lower().startswith("torso")), None)
    if args.center == "bbox" or torso is None:
        center_units = 0.5 * (min(xs) + max(xs))
    elif args.center == "torso":
        center_units = 0.5 * (torso["world_bbox"][0] + torso["world_bbox"][2])
    elif args.center == "feet":
        feet = [p for p in parts_in if p["name"].lower().startswith("foot")] or parts_in
        center_units = 0.5 * (min(p["world_bbox"][0] for p in feet)
                              + max(p["world_bbox"][2] for p in feet))
    else:
        center_units = float(args.center)
    origin = (stage_w * 0.5 - center_units * ppu, args.feet_y + min(ys) * ppu)

    def to_stage(point):
        return (origin[0] + point[0] * ppu, origin[1] - point[1] * ppu)

    # 3. bones: rest position relative to the parent's head
    bone_index = {b["name"]: i for i, b in enumerate(bones_in)}
    heads = {b["name"]: to_stage(b["head"]) for b in bones_in}
    bones_out = []
    for bone in bones_in:
        parent = bone["parent"]
        head = heads[bone["name"]]
        if parent is None:
            rest = head
        else:
            ph = heads[parent]
            rest = (head[0] - ph[0], head[1] - ph[1])
        bones_out.append({"name": bone["name"], "parent": parent,
                          "rest": [round(rest[0], 2), round(rest[1], 2)],
                          "angle": 0.0})   # filled in by the attached part
    bone_by_name = {b["name"]: b for b in bones_out}

    # 4. parts: sprite box, pivot (bone head inside the image), angle, order
    parts_out = []
    for order, part in enumerate(sorted(parts_in, key=lambda p: (p["z"], p["name"]))):
        name = part["name"]
        bone = name if name in bone_by_name else bones_out[0]["name"]
        w, h = part_size_units(part)
        sprite_w = max(1, int(round(w * ppu)))
        sprite_h = max(1, int(round(h * ppu)))

        joint_world = bones_in[bone_index[bone]]["head"]
        local = world_to_local(part, joint_world)
        lx0, ly0, lx1, ly1 = part["local"]
        pivot = ((local[0] - lx0) / (lx1 - lx0) * sprite_w,
                 (ly1 - local[1]) / (ly1 - ly0) * sprite_h)

        if args.angles == "bone":
            tail = bones_in[bone_index[bone]]["tail"]
            direction = (tail[0] - joint_world[0], tail[1] - joint_world[1])
            angle = math.degrees(math.atan2(direction[1], direction[0])) + 90.0
        else:
            angle = -part["rot_z_deg"]
        angle = (angle + 180.0) % 360.0 - 180.0
        bone_by_name[bone]["angle"] = round(angle, 2)

        with Image.open(part["image_path"]) as img:
            png_w, png_h = img.size
        parts_out.append({
            "name": name,
            "bone": bone,
            "image": os.path.relpath(part["image_path"],
                                     os.path.dirname(os.path.abspath(args.out))).replace("\\", "/"),
            "png_size": [png_w, png_h],
            "sprite": [sprite_w, sprite_h],
            "pivot": [round(pivot[0], 2), round(pivot[1], 2)],
            "angle": round(angle, 2),
            "draw_order": order,
            "z": part["z"],
        })

    return {
        "id": args.id,
        "stage": {"w": stage_w, "h": stage_h},
        "fit": {
            "units_height": round(units_h, 6),
            "ppu": round(ppu, 6),
            "origin": [round(origin[0], 6), round(origin[1], 6)],
            "height_frac": args.height_frac,
            "feet_y": args.feet_y,
            "center": str(args.center),
            "angles": args.angles,
        },
        "source": {
            "blend": scene.get("blend"),
            "blender": scene.get("blender"),
            "scene_json": os.path.relpath(os.path.abspath(args.scene),
                                          os.path.dirname(os.path.abspath(args.out))).replace("\\", "/"),
        },
        "bones": bones_out,
        "parts": parts_out,
    }


# --------------------------------------------------------------------------- #

def preview(rig: dict, base_dir: str, out_path: str, scale: int = 3) -> None:
    """Render of the rig at rest: sprites + bones + joints, for visual checking.

    Drawing goes through the shared blitter (`iska_common.blit_part`), so this
    preview is a **faithful** rendering of the engine: if it is wrong, the runtime
    is wrong too.
    """
    skeleton = iska.Skeleton(rig)
    width, height = skeleton.stage_w, skeleton.stage_h
    buf = iska.new_frame(width, height, iska.rgb_to_565(18, 18, 24))

    sprites = {}
    for part in rig["parts"]:
        with Image.open(os.path.join(base_dir, part["image"])) as img:
            sw, sh = part["sprite"]
            sprites[part["name"]] = (iska.image_to_sprite(img, (sw, sh)), sw, sh)
    skeleton.draw(buf, skeleton.rest_pose(), sprites)

    canvas = Image.new("RGB", (width, height))
    px = canvas.load()
    for y in range(height):
        row = y * width
        for x in range(width):
            px[x, y] = iska.rgb565_to_rgb(buf[row + x])

    draw = ImageDraw.Draw(canvas)
    joints = skeleton.resolve_bones(skeleton.rest_pose())
    for i, bone in enumerate(skeleton.bones):
        jx, jy = joints[i][0], joints[i][1]
        parent = bone["parent"]
        if parent is not None:
            pj = joints[skeleton.index[parent]]
            draw.line([(pj[0], pj[1]), (jx, jy)], fill=(90, 200, 255), width=1)
    for i, _bone in enumerate(skeleton.bones):
        jx, jy = joints[i][0], joints[i][1]
        draw.ellipse([jx - 2, jy - 2, jx + 2, jy + 2], outline=(255, 96, 96))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    canvas.resize((width * scale, height * scale), Image.NEAREST).save(out_path)
    print(f"[rig_build] rig preview (x{scale}) -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scene", help="JSON produced by tools/blender_export.py")
    ap.add_argument("--id", default="rabbit3")
    ap.add_argument("--out", required=True, help="rig JSON to write")
    ap.add_argument("--stage-w", type=int, default=240)
    ap.add_argument("--stage-h", type=int, default=320)
    ap.add_argument("--height-frac", type=float, default=0.64,
                    help="character height as a fraction of the panel height")
    ap.add_argument("--feet-y", type=int, default=300,
                    help="y (px) of the feet line")
    ap.add_argument("--center", default="feet",
                    help="feet (default) | bbox | torso | value in Blender units")
    ap.add_argument("--angles", choices=("plane", "bone"), default="plane",
                    help="origin of the rest angle: Blender plane or bone direction")
    ap.add_argument("--preview", default=None, help="control PNG of the rig at rest")
    args = ap.parse_args()

    with open(args.scene, encoding="utf-8") as fh:
        scene = json.load(fh)
    rig = build(scene, args)

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(rig, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    fit = rig["fit"]
    print(f"[rig_build] {len(rig['bones'])} bones, {len(rig['parts'])} parts -> {out_path}")
    print(f"[rig_build] {fit['units_height']:.3f} units -> {fit['ppu']:.3f} px/unit "
          f"(character {fit['units_height'] * fit['ppu']:.1f} px tall), "
          f"origin ({fit['origin'][0]:.1f}, {fit['origin'][1]:.1f})")
    for part in rig["parts"]:
        print(f"[rig_build]   {part['name']:6s} bone={part['bone']:6s} "
              f"box={part['sprite'][0]}x{part['sprite'][1]} "
              f"pivot=({part['pivot'][0]:.1f},{part['pivot'][1]:.1f}) "
              f"angle={part['angle']:+.1f} order={part['draw_order']}")
    for bone in rig["bones"]:
        print(f"[rig_build]   bone {bone['name']:6s} parent={str(bone['parent']):6s} "
              f"rest=({bone['rest'][0]:+.1f},{bone['rest'][1]:+.1f}) "
              f"angle={bone['angle']:+.1f}")

    if args.preview:
        preview(rig, os.path.dirname(out_path), args.preview)


if __name__ == "__main__":
    main()
