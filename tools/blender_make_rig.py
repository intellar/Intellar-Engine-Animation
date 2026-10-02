"""Creates (or refreshes) the character's armature in a .blend, headless.

    blender -b tools/source/rabbit3.blend --python tools/blender_make_rig.py -- \
        --bones tools/rigs/rabbit3_bones.json \
        --out tools/source/rabbit3_rig.blend

The character's planes were placed by hand in Blender ("Images as Planes"); this
script places over them the **bone heads** deduced from those planes (see
`anchor` in the seed JSON), links the bones together, then saves a copy of the
.blend. It is a STARTING POINT: the armature is then adjusted with the mouse in
Blender (`rabbit3_rig.blend` is the reference for the skeleton).

Once the armature is adjusted, the export is done with `tools/blender_export.py`
(which reads back the bone heads, not the seeds).

If an armature with the same name already exists, it is **deleted** then
recreated: the script is idempotent (handy to start over from the seeds).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import bpy                      # noqa: E402  (provided by Blender)
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


def norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def meshes_by_name() -> dict:
    """Planes usable as parts: mesh with an image in its materials."""
    found = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        found[obj.name] = obj
        found.setdefault(norm(obj.name), obj)
    return found


def local_rect(obj):
    """Local rectangle of the plane: read from the mesh (not through `obj.bound_box`,
    whose cache is not reliable here: it returns wild values depending on the order
    of the reads, even in object mode)."""
    verts = [v.co for v in obj.data.vertices]
    if not verts:                       # mesh without any vertex: fall back on the cache
        verts = [Vector(c) for c in obj.bound_box]
    return (min(v.x for v in verts), min(v.y for v in verts),
            max(v.x for v in verts), max(v.y for v in verts))


def anchor_world(obj, anchor) -> Vector:
    lx0, ly0, lx1, ly1 = local_rect(obj)
    ax, ay = anchor
    local = Vector((lx0 + ax * (lx1 - lx0), ly0 + ay * (ly1 - ly0), 0.0))
    return obj.matrix_world @ local


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bones", default="tools/rigs/rabbit3_bones.json")
    ap.add_argument("--out", default="tools/source/rabbit3_rig.blend")
    args = ap.parse_args(argv_after_dashdash())

    with open(resolve(args.bones), encoding="utf-8") as fh:
        seeds = json.load(fh)

    parts = meshes_by_name()
    length = float(seeds.get("bone_length", 0.35))
    arm_name = seeds.get("armature", "skeleton")

    # Idempotence: start over from a brand-new armature.
    old = bpy.data.objects.get(arm_name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)

    # Measurements BEFORE entering edit mode: Blender does not re-evaluate the box
    # of the other objects while an object is being edited (bound_box is empty or
    # wild there).
    heads = {}
    tails = {}
    for seed in seeds["bones"]:
        part = parts.get(seed["part"]) or parts.get(norm(seed["part"]))
        if part is None:
            print(f"[make_rig] no plane found for bone {seed['name']} ({seed['part']})")
            continue
        head = anchor_world(part, seed["anchor"])
        direction = Vector((seed["dir"][0], seed["dir"][1], 0.0))
        if direction.length == 0:
            direction = Vector((0.0, 1.0, 0.0))
        heads[seed["name"]] = head
        tails[seed["name"]] = head + direction.normalized() * length

    arm_data = bpy.data.armatures.new(arm_name)
    arm_obj = bpy.data.objects.new(arm_name, arm_data)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)

    bpy.ops.object.mode_set(mode="EDIT")
    made = {}
    for seed in seeds["bones"]:
        if seed["name"] not in heads:
            continue
        edit_bone = arm_data.edit_bones.new(seed["name"])
        edit_bone.head = heads[seed["name"]]
        edit_bone.tail = tails[seed["name"]]
        made[seed["name"]] = edit_bone
    for seed in seeds["bones"]:
        bone = made.get(seed["name"])
        if bone is None or not seed["parent"]:
            continue
        parent = made.get(seed["parent"])
        if parent is None:
            print(f"[make_rig] unknown parent for {seed['name']}: {seed['parent']}")
            continue
        bone.parent = parent
    bpy.ops.object.mode_set(mode="OBJECT")

    out_path = os.path.abspath(resolve(args.out))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out_path)
    print(f"[make_rig] {len(made)} bones -> {out_path}")
    # NB: `heads` is printed (measured before the edit) and not the `edit_bones`:
    # after switching back to object mode, those handles point to freed memory.
    for seed in seeds["bones"]:
        head = heads.get(seed["name"])
        if head is not None:
            print(f"[make_rig]   {seed['name']:6s} head=({head.x:+.3f}, {head.y:+.3f}) "
                  f"parent={seed['parent']}")


main()
