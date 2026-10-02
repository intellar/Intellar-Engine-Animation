"""Exports the plane placement and the skeleton of a .blend to a JSON file.

    blender -b tools/source/rabbit3_rig.blend --python tools/blender_export.py -- \
        --out build/rabbit3/scene.json

The JSON produced is the **contract** between Blender and the rest of the chain:
for each plane (part) it contains:

  - its **local** box (`local`): rectangle, not rotated, not scaled;
  - its 4x4 world matrix (`matrix`, row by row): position + Z rotation + uniform
    scale set by hand in Blender;
  - its world box (`world_bbox`): bounding rectangle, after rotation;
  - the name of its image (`image`, `image_path`);
  - its Z (`z`): draw order (larger = more in front).

And, if an armature is present, its bones (`armature.bones`): name, parent, head
and tail in **world** coordinates (it is the head that becomes the joint of the
engine skeleton). Pose actions are listed (`actions`) for information: they are
not baked into keyframes yet (animations are written in JSON, see
`tools/animations/`).

This script only reads the scene: it writes nothing into the .blend.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import bpy                       # noqa: E402  (provided by Blender)
from mathutils import Vector     # noqa: E402


def argv_after_dashdash() -> list:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


# Blender is not always started from the repository (a double click starts it in
# its own folder), and a script run from a Text block has its folder reported as
# `<something>.blend/`: the search walks up from the script, then from the .blend
# that is open, until it finds the root of the repository (`tools/` + `src/`).
def repo_root() -> str:
    here = globals().get("__file__") or ""
    starts = [os.path.dirname(os.path.abspath(here)) if here else "",
              os.path.dirname(os.path.abspath(bpy.data.filepath))
              if bpy.data.filepath else "", os.getcwd()]
    for start in starts:
        folder = os.path.abspath(start)
        while True:
            if (os.path.isdir(os.path.join(folder, "tools"))
                    and os.path.isdir(os.path.join(folder, "src"))):
                return folder
            parent = os.path.dirname(folder)
            if parent == folder:                # top of the drive: nothing found
                break
            folder = parent
    return os.getcwd()


ROOT = repo_root()


def resolve(path: str) -> str:
    """A relative path is read from the root of the repository (as in the README);
    an absolute path is kept as it is."""
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def object_mode() -> None:
    """The scripts work in Object mode, and a .blend can be saved in Edit mode.

    Blender restores the mode of the file it loads: opened while the armature was
    being edited, it starts in Edit mode -- and there Blender **does not evaluate
    the pose**, so the bones read as if they were at rest and a posed armature
    would not be reported (the pose is exported as the reference placement).
    """
    active = bpy.context.view_layer.objects.active
    if bpy.context.mode == "OBJECT" or active is None or active.mode == "OBJECT":
        return
    print(f"[blender_export] {active.name} is in Edit mode ({bpy.context.mode}): "
          f"switching to Object mode (Blender does not evaluate the pose while "
          f"editing)")
    bpy.ops.object.mode_set(mode="OBJECT")


def image_of(obj):
    """(name, resolved path) of the first image found in the materials."""
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue
        tree = getattr(mat, "node_tree", None)   # not `use_nodes` (deprecated in 5.x)
        if tree is None:
            continue
        for node in tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                img = node.image
                raw = img.filepath or ""
                if raw.startswith("//"):
                    raw = os.path.join(os.path.dirname(bpy.data.filepath), raw[2:])
                return img.name, (os.path.abspath(raw) if raw else "")
    return "", ""


def dump_part(obj) -> dict:
    corners = [Vector(c) for c in obj.bound_box]
    local = [min(c.x for c in corners), min(c.y for c in corners),
             max(c.x for c in corners), max(c.y for c in corners)]
    world = [obj.matrix_world @ c for c in corners]
    image, image_path = image_of(obj)
    matrix = obj.matrix_world
    return {
        "name": obj.name,
        "image": image,
        "image_path": image_path,
        "local": [round(v, 6) for v in local],
        "matrix": [[round(matrix[r][c], 6) for c in range(4)] for r in range(4)],
        "world_bbox": [round(min(v.x for v in world), 6), round(min(v.y for v in world), 6),
                       round(max(v.x for v in world), 6), round(max(v.y for v in world), 6)],
        "z": round(sum(v.z for v in world) / len(world), 6),
        "rot_z_deg": round(obj.rotation_euler.z * 57.29577951308232, 4),
        "scale_xyz": [round(v, 6) for v in obj.scale],
        "parent": obj.parent.name if obj.parent else None,
        "parent_bone": obj.parent_bone or None,
    }


def posed_bones(arm_obj) -> list:
    """Pose bones that are **not** at rest.

    The export reads the planes where they are: on a file whose planes are bound
    to the armature (the animation file), a leftover pose would be exported as the
    new rest placement -- a silent and very confusing change. `main` refuses to
    export in that case (unless `--allow-pose`).
    """
    if arm_obj is None:
        return []
    out = []
    for pose_bone in arm_obj.pose.bones:
        euler = pose_bone.rotation_euler
        if (pose_bone.location.length > 1e-6
                or abs(pose_bone.rotation_quaternion.angle) > 1e-6
                or max(abs(euler.x), abs(euler.y), abs(euler.z)) > 1e-6
                or abs(pose_bone.scale.x - 1.0) > 1e-6
                or abs(pose_bone.scale.y - 1.0) > 1e-6
                or abs(pose_bone.scale.z - 1.0) > 1e-6):
            out.append(pose_bone.name)
    return out


def dump_armature():
    arm_obj = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm_obj is None:
        return None
    mw = arm_obj.matrix_world
    bones = []
    for bone in arm_obj.data.bones:
        head = mw @ bone.head_local
        tail = mw @ bone.tail_local
        bones.append({
            "name": bone.name,
            "parent": bone.parent.name if bone.parent else None,
            "head": [round(head.x, 6), round(head.y, 6)],
            "tail": [round(tail.x, 6), round(tail.y, 6)],
            "head_local": [round(v, 6) for v in bone.head_local],
            "tail_local": [round(v, 6) for v in bone.tail_local],
        })
    return {"name": arm_obj.name,
            "matrix": [[round(mw[r][c], 6) for c in range(4)] for r in range(4)],
            "posed_bones": posed_bones(arm_obj),
            "bones": bones}


def action_fcurves(act) -> list:
    """The F-curves of an action.

    `act.fcurves` up to Blender 4.3; after that an action is *slotted* and its
    curves live in the channelbag of each layer -- `Action.fcurves` was removed in
    5.x, where reading it raises `AttributeError` (the documented exports of the
    rig all have zero actions, so this only shows up on `rabbit3_anim.blend`).
    """
    legacy = getattr(act, "fcurves", None)
    if legacy is not None:
        return list(legacy)
    out = []
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                out.extend(bag.fcurves)
    return out


def dump_actions() -> list:
    out = []
    for act in bpy.data.actions:
        targets = set()
        for fc in action_fcurves(act):
            path = fc.data_path
            if path.startswith('pose.bones["'):
                targets.add(path.split('"')[1])
        out.append({
            "name": act.name,
            "frame_range": [round(v, 3) for v in act.frame_range],
            "fcurves": len(action_fcurves(act)),
            "pose_bones": sorted(targets),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    # `--out` MUST have a default: a Text block run from inside Blender cannot
    # take arguments (README, "Running the scripts"), and argparse calls sys.exit
    # on a missing required argument -- which quits Blender on the spot.
    ap.add_argument("--out", default="build/rabbit3/scene.json",
                    help="exported JSON (default: build/rabbit3/scene.json)")
    ap.add_argument("--allow-pose", action="store_true",
                    help="export even if the armature is posed (the pose becomes "
                         "the reference placement of the rig)")
    args = ap.parse_args(argv_after_dashdash())

    object_mode()
    parts = [dump_part(o) for o in bpy.data.objects
             if o.type == "MESH" and image_of(o)[0]]
    parts.sort(key=lambda p: p["z"])

    data = {
        "blender": bpy.app.version_string,
        "blend": os.path.abspath(bpy.data.filepath),
        "units": "Blender (1 unit = 1 reference plane; see tools/rig_build.py)",
        "parts": parts,
        "armature": dump_armature(),
        "actions": dump_actions(),
    }

    # A leftover pose only matters when planes are bound to the armature (the
    # animation file): it would silently become the reference placement.
    armature = data["armature"]
    posed = armature["posed_bones"] if armature else []
    bound = [p for p in parts if armature and p["parent"] == armature["name"]]
    if posed and bound and not args.allow_pose:
        shown = ", ".join(posed[:4]) + ("..." if len(posed) > 4 else "")
        raise SystemExit(
            f"[blender_export] the armature is posed ({shown}) and {len(bound)} "
            f"plane(s) are bound to it: what is exported now becomes the rest pose "
            f"of the rig. Reset the pose in Blender (Pose mode, Alt+G / Alt+R / "
            f"Alt+S), or pass --allow-pose if that pose IS the reference.")
    if posed and bound:
        print(f"[blender_export] --allow-pose: the pose ({', '.join(posed)}) is "
              f"exported as the reference placement")
    elif posed:
        print(f"[blender_export] note: the armature is posed ({', '.join(posed)}) but "
              f"no plane is bound to it: the exported placement is unaffected")

    # The engine binds a plane to the bone with the **same exact name**
    # (`tools/rig_build.py`) and attaches a plane that matches nothing to the root
    # bone, silently. Blender's "Armature > Names > Auto-Side Names" appends a
    # `.L`/`.R` suffix to the *selected* bones, which breaks that match: say it
    # here, before the JSON leaves for the engine.
    if armature:
        root = next((b for b in armature["bones"] if b["parent"] is None), None)
        named = {part["name"] for part in parts}
        for bone in armature["bones"]:
            name = bone["name"]
            if bone is root or name in named:
                continue
            base = name[:-2] if name[-2:] in (".L", ".R") else name
            if base != name and base in named:
                print(f"[blender_export] WARNING: bone {name!r} matches no plane: the "
                      f"engine would attach the plane {base!r} to the root bone. "
                      f"Blender's Auto-Side Names adds the `.L`/`.R` suffix -- rename "
                      f"the bone (or the plane) back to {base!r} before building the "
                      f"asset.")
            else:
                print(f"[blender_export] note: bone {name!r} has no same-named plane "
                      f"(the engine attaches such a plane to the root bone)")

    out_path = os.path.abspath(resolve(args.out))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"[blender_export] {len(parts)} planes, "
          f"{len(data['armature']['bones']) if data['armature'] else 0} bones, "
          f"{len(data['actions'])} actions -> {out_path}")
    for part in parts:
        print(f"[blender_export]   {part['name']:6s} z={part['z']:+.2f} "
              f"rot={part['rot_z_deg']:+.1f}deg local={part['local']}")


main()
