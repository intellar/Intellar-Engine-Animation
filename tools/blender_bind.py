"""Binds the planes to the bones, so that the .blend behaves like the engine.

    blender -b tools/source/rabbit3_rig.blend --python tools/blender_bind.py -- \
        --out tools/source/rabbit3_anim.blend

Out of the box Blender keeps the armature and the sprites independent: moving a
bone does not move a plane. This script turns the rig into a **posable preview**
that follows the same rules as the engine:

* every plane is parented to the bone with **the same exact name** (that is how
  the engine binds them, `tools/rig_build.py`). A plane without a same-named bone
  is left alone and reported: the engine would attach it to the root bone;
* `inherit_scale = 'NONE'` on every bone: the engine deliberately does **not**
  inherit the scale of a parent (docs/FORMAT.md), so shrinking the torso pulls the
  head down without deforming it. This is what makes Blender and the panel agree;
* the leftover pose is cleared by default (`--keep-pose` to keep it): the planes
  are authored at rest, a pose saved by accident would be bound as if it were the
  rest pose.

`--verify` (on by default) proves the binding on the spot: every bone that owns a
plane is rotated and its plane must follow; then the root bone is scaled and no
plane may change size (that is the engine rule).

The result is saved to `--out`, **never in place**: `tools/source/rabbit3_rig.blend`
stays the reference of the skeleton.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import bpy                                  # noqa: E402  (provided by Blender)
from mathutils import Matrix, Quaternion, Vector    # noqa: E402


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
    the pose**. Every plane bound to a bone then looks frozen, so the checks below
    would report a broken binding (`0/9 joints follow`) that is not there.
    """
    active = bpy.context.view_layer.objects.active
    if bpy.context.mode == "OBJECT" or active is None or active.mode == "OBJECT":
        return
    print(f"[blender_bind] {active.name} is in Edit mode ({bpy.context.mode}): "
          f"switching to Object mode (Blender does not evaluate the pose while "
          f"editing, so the binding could not be checked)")
    bpy.ops.object.mode_set(mode="OBJECT")


def armature():
    return next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)


def image_of(obj) -> str:
    for slot in obj.material_slots:
        mat = slot.material
        tree = getattr(mat, "node_tree", None) if mat else None
        if tree is None:
            continue
        for node in tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                return node.image.name
    return ""


def planes() -> list:
    return sorted((o for o in bpy.data.objects
                   if o.type == "MESH" and image_of(o)), key=lambda o: o.name)


def update() -> None:
    bpy.context.view_layer.update()


def snapshot_pose(arm) -> dict:
    """Everything needed to put the armature back exactly as it was."""
    return {pb.name: (pb.rotation_mode, pb.location.copy(),
                      pb.rotation_quaternion.copy(), pb.rotation_euler.copy(),
                      pb.scale.copy()) for pb in arm.pose.bones}


def restore_pose(arm, snap: dict) -> None:
    for pb in arm.pose.bones:
        mode, location, quaternion, euler, scale = snap[pb.name]
        pb.rotation_mode = mode
        pb.location = location
        pb.rotation_quaternion = quaternion
        pb.rotation_euler = euler
        pb.scale = scale
    update()


def reset_pose(arm) -> list:
    """Clears every transform (Alt+G / Alt+R / Alt+S on all bones)."""
    moved = []
    for pb in arm.pose.bones:
        if (pb.location.length > 1e-6 or pb.scale != Vector((1.0, 1.0, 1.0))
                or abs(pb.rotation_quaternion.angle) > 1e-6
                or max(abs(value) for value in pb.rotation_euler) > 1e-6):
            moved.append(pb.name)
        pb.matrix_basis = Matrix.Identity(4)
    update()
    return moved


def rotate_bone(pb, degrees: float) -> None:
    """Small rotation around Z (screen plane), whatever the rotation mode is."""
    if pb.rotation_mode == "QUATERNION":
        pb.rotation_quaternion = Quaternion((0.0, 0.0, 1.0), math.radians(degrees))
    else:
        pb.rotation_euler.z = math.radians(degrees)


def world_matrix(obj) -> tuple:
    return tuple(round(value, 5) for row in obj.matrix_world for value in row)


def world_size(obj) -> tuple:
    """Size (x, y) of the plane in world units, whatever its rotation is."""
    verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not verts:
        return (0.0, 0.0)
    xs = [v.x for v in verts]
    ys = [v.y for v in verts]
    return (round(max(xs) - min(xs), 5), round(max(ys) - min(ys), 5))


def bind(obj, arm, bone_name: str) -> bool:
    """Parents a plane to a bone **without moving it** (the placement is kept)."""
    # Compare by name: a second read of `obj.parent` gives a new Python wrapper,
    # so `is` is not a reliable test on RNA structs.
    if (obj.parent is not None and obj.parent.name == arm.name
            and obj.parent_bone == bone_name):
        return False                        # already bound: nothing to do
    world = obj.matrix_world.copy()
    obj.parent = arm
    obj.parent_type = "BONE"
    obj.parent_bone = bone_name
    update()                                # the bone matrix must be up to date...
    obj.matrix_world = world                # ...before restoring the placement
    update()
    drift = max(abs(world[r][c] - obj.matrix_world[r][c])
                for r in range(4) for c in range(4))
    if drift > 1e-4:
        print(f"[blender_bind] WARNING: binding {obj.name} moved it by {drift:.5f} "
              f"-- check the bone it is bound to")
    return True


def inherit_scale_none(arm) -> int:
    """The engine does not inherit the scale of a parent (docs/FORMAT.md)."""
    changed = 0
    for pb in arm.pose.bones:
        if pb.bone.inherit_scale != "NONE":
            pb.bone.inherit_scale = "NONE"
            changed += 1
    return changed


def verify(arm, bound_pairs: list) -> int:
    """Proves on the spot that the .blend follows the engine's rules.

    Three checks, measured on the bound planes and the pose bones:

    1. **binding**: every bone that owns a plane is rotated by 8 deg and its plane
       must follow. A plane bound to the wrong bone (or to nothing) looks perfectly
       fine in the viewport, so this is the one mistake worth catching here;
    2. **scale**: the root is scaled by 1.5. The engine rule (docs/FORMAT.md) is

           world_pos   = parent_pos + R(parent_angle) * (parent_scale (.) local_rest)
           world_scale = local_scale                    (never inherited)

       so no plane may change size, a child of the root must move by
       `(1.5 - 1) * its rest offset`, and any deeper bone must move exactly like its
       parent (its parent's scale is 1: nothing is scaled twice);
    3. **rotation**: the root is rotated by 10 deg -- the character is rigid, so the
       distance between two planes must not change.
    """
    failures = 0
    snap = snapshot_pose(arm)

    following = 0
    for pb, obj in bound_pairs:
        before = world_matrix(obj)
        rotate_bone(pb, 8.0)
        update()
        if world_matrix(obj) != before:
            following += 1
        else:
            failures += 1
            print(f"[blender_bind] verify  bone {pb.name:8s} -> plane {obj.name:8s} "
                  f"DOES NOT FOLLOW (wrong binding)")
        restore_pose(arm, snap)
    print(f"[blender_bind] verify  binding: {following}/{len(bound_pairs)} bones move "
          f"their own plane")

    root = next((pb for pb in arm.pose.bones if pb.parent is None), None)
    if root is None:
        return failures

    # 2. the engine's scale rule
    scale = 1.5
    sizes = {obj.name: world_size(obj) for _pb, obj in bound_pairs}
    joints = {pb.name: (arm.matrix_world @ pb.head).copy() for pb in arm.pose.bones}
    root.scale = Vector((scale, scale, 1.0))
    update()
    deformed = [obj.name for _pb, obj in bound_pairs
                if world_size(obj) != sizes[obj.name]]
    moves = {pb.name: (arm.matrix_world @ pb.head) - joints[pb.name]
             for pb in arm.pose.bones}
    restore_pose(arm, snap)

    if deformed:
        failures += 1
        print(f"[blender_bind] verify  scale x{scale}: {deformed} changed size -- the "
              f"scale IS inherited, Blender would not match the engine")
    else:
        print(f"[blender_bind] verify  scale x{scale}: no plane changed size "
              f"(the scale is not inherited)")

    checked = 0
    for pb in arm.pose.bones:               # parents come before children
        if pb.parent is None:
            continue
        if pb.parent.name == root.name:
            offset = joints[pb.name] - joints[root.name]
            local = arm.matrix_world.inverted().to_3x3() @ offset
            expected = arm.matrix_world.to_3x3() @ Vector(
                ((scale - 1.0) * local.x, (scale - 1.0) * local.y, 0.0))
        else:
            expected = moves[pb.parent.name]
        delta = moves[pb.name]
        checked += 1
        if (delta - expected).length > 1e-3:
            failures += 1
            print(f"[blender_bind] verify  scale x{scale}: {pb.name} moved by "
                  f"({delta.x:+.4f},{delta.y:+.4f}) instead of "
                  f"({expected.x:+.4f},{expected.y:+.4f}) -- the engine rule "
                  f"(parent_scale * local_rest) is not reproduced")
    print(f"[blender_bind] verify  scale x{scale}: {checked} joints checked against "
          f"the engine rule (parent_pos + parent_scale * local_rest)")

    # 3. a rotation is rigid
    origins = {obj.name: obj.matrix_world.translation.copy() for _pb, obj in bound_pairs}
    rotate_bone(root, 10.0)
    update()
    turned = {obj.name: obj.matrix_world.translation.copy() for _pb, obj in bound_pairs}
    restore_pose(arm, snap)
    names = list(origins)
    worst = 0.0
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            worst = max(worst, abs((turned[first] - turned[second]).length
                                   - (origins[first] - origins[second]).length))
    if worst > 1e-3:
        failures += 1
        print(f"[blender_bind] verify  rotation 10 deg: NOT rigid (distances changed "
              f"by up to {worst:.5f})")
    else:
        print(f"[blender_bind] verify  rotation 10 deg: rigid, the joints follow their "
              f"parents (worst distance change {worst:.6f})")
    return failures


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("tools", "source", "rabbit3_anim.blend"),
                    help="where to save the bound .blend (never in place)")
    ap.add_argument("--keep-pose", action="store_true",
                    help="bind the current pose instead of clearing it first")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the binding/scale verification")
    args = ap.parse_args(argv_after_dashdash())

    object_mode()
    arm = armature()
    if arm is None:
        raise SystemExit("[blender_bind] no armature in this .blend")
    parts = planes()
    if not parts:
        raise SystemExit("[blender_bind] no plane (mesh with an image) in this .blend")

    posed = [pb.name for pb in arm.pose.bones
             if pb.location.length > 1e-6 or pb.scale != Vector((1.0, 1.0, 1.0))
             or abs(pb.rotation_quaternion.angle) > 1e-6
             or max(abs(value) for value in pb.rotation_euler) > 1e-6]
    if posed and not args.keep_pose:
        print(f"[blender_bind] clearing the leftover pose ({', '.join(posed)}): the "
              f"planes are authored at rest (`--keep-pose` to bind the pose as is)")
        reset_pose(arm)
    elif posed:
        print(f"[blender_bind] the armature stays posed ({', '.join(posed)}): the "
              f"placement is kept, but clearing the pose later will move the planes")

    bone_names = [bone.name for bone in arm.data.bones]
    bound_pairs = []
    for obj in parts:
        if obj.name not in bone_names:
            print(f"[blender_bind] plane {obj.name:10s} has NO same-named bone: left "
                  f"unbound (the engine would attach it to the root bone)")
            continue
        fresh = bind(obj, arm, obj.name)
        bound_pairs.append((arm.pose.bones[obj.name], obj))
        print(f"[blender_bind] plane {obj.name:10s} -> bone {obj.name:10s} "
              f"{'bound' if fresh else 'was already bound'}")

    changed = inherit_scale_none(arm)
    print(f"[blender_bind] inherit_scale = NONE on {changed} bone(s) "
          f"(the engine does not inherit the scale of a parent)")

    failures = 0 if args.no_verify else verify(arm, bound_pairs)

    out_path = os.path.abspath(resolve(args.out))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out_path)
    print(f"[blender_bind] {len(bound_pairs)}/{len(parts)} planes bound -> {out_path}")
    print("[blender_bind] next: python tools/build_asset.py --to-blender   "
          "(or tools/blender_import_anims.py to add the animations)")
    if failures:
        raise SystemExit(f"[blender_bind] {failures} verification failure(s): the file "
                         f"was saved, but the rig is NOT trustworthy")


main()
