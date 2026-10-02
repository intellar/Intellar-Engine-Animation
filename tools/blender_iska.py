"""Engine <-> Blender maths, shared by the Blender scripts of the chain.

Imported by `tools/blender_bind.py`, `tools/blender_import_anims.py` and
`tools/blender_bake_anims.py` (never run directly): the conversions live in one
place, so both directions of the round trip use exactly the same formulas.

    engine (paper)   x right, **y down**, angles in degrees **clockwise**,
                     240x320 px, `shape = Joint + R(angle) * (Scale * (p - Pivot))`
    Blender (3D)     x right, **y up**, angles counter-clockwise, 1 unit = 1 plane

The rig JSON records the mapping computed by `tools/rig_build.py` (`fit.ppu`,
`fit.origin`), so nothing is guessed:

    stage_x = origin_x + x * ppu            x = (stage_x - origin_x) / ppu
    stage_y = origin_y - y * ppu            y = (origin_y - stage_y) / ppu

A **pose** is a list of `(dx, dy, rot, sx, sy)` per bone, deltas from the rest pose
(see docs/FORMAT.md). Both directions go through `iska_common.Skeleton`, i.e. the
engine's own implementation: the tooling cannot drift away from the runtime without
`tools/iska_clip_check.py` failing.

The one thing that is *not* exactly representable: the engine scales a part along
**the part's own axes**, whereas a Blender bone scales along the **bone's** axes.
They coincide when the sprite is not rotated relative to its bone (`rot_z = 0` at
rest, the usual case, and the only case the shipped animations use for a
non-uniform scale). `sprite_bone_angles()` reports the bones where they differ.
"""
from __future__ import annotations

import math

import iska_common as iska

DEG = math.degrees
RAD = math.radians


def stage_to_blender(rig: dict, x: float, y: float):
    """Engine pixels -> Blender units (the y axis is flipped)."""
    ppu = rig["fit"]["ppu"]
    origin_x, origin_y = rig["fit"]["origin"]
    return ((x - origin_x) / ppu, (origin_y - y) / ppu)


def blender_to_stage(rig: dict, x: float, y: float):
    """Blender units -> engine pixels (the y axis is flipped)."""
    ppu = rig["fit"]["ppu"]
    origin_x, origin_y = rig["fit"]["origin"]
    return (origin_x + x * ppu, origin_y - y * ppu)


def rest_world_angles(skeleton) -> dict:
    """Cumulative rest angle (engine sign) of every bone: `sum` along the chain."""
    out = {}
    for bone in skeleton.bones:
        own = float(bone.get("angle") or 0.0)
        parent = bone["parent"]
        out[bone["name"]] = own + (out[parent] if parent else 0.0)
    return out


def frame_angle(matrix) -> float:
    """Angle of a matrix's X axis in the screen plane, in **engine** degrees.

    The engine counts clockwise on a y-down screen, Blender counter-clockwise on a
    y-up one: one sign flip converts them (`tools/rig_build.py` does the same with
    `angle = -rot_z`). Reading the X axis is robust to a diagonal scale, which does
    not turn the axis.
    """
    return -DEG(math.atan2(matrix[1][0], matrix[0][0]))


def axis_lengths(matrix):
    """(sx, sy) of a matrix: the length of its X and Y axes."""
    return (math.hypot(matrix[0][0], matrix[1][0]),
            math.hypot(matrix[0][1], matrix[1][1]))


def bound_parts(arm) -> dict:
    """`{bone name: plane}` for the planes bound to the armature (`parent_bone`)."""
    found = {}
    for obj in arm.children:
        if obj.type == "MESH" and obj.parent_bone:
            found[obj.parent_bone] = obj
    return found


def measure(arm, pairs: dict, resting=None) -> dict:
    """World state of every pose bone, in engine terms.

    `{"pos": (blender x, blender y), "angle": engine degrees, "scale": (sx, sy)}`
    per bone name. The angle and the scale are read from the **plane** when one is
    bound (it is the part the engine draws), and from the bone otherwise.

    Pass `resting` (the same call made at rest) to get the **engine scale**: the
    engine's `sx/sy` is what the part became compared to the rest pose, it is not
    the plane's absolute scale in the .blend (a plane is often 1.6 units wide where
    the sprite box is only there to be stretched in the reference pose).
    """
    out = {}
    for pose_bone in arm.pose.bones:
        plane = pairs.get(pose_bone.name)
        source = plane.matrix_world if plane is not None else arm.matrix_world @ pose_bone.matrix
        head = arm.matrix_world @ pose_bone.head
        if plane is not None:
            scale = axis_lengths(plane.matrix_world)
        else:
            scale = (abs(pose_bone.scale.x), abs(pose_bone.scale.y))
        reference = (resting or {}).get(pose_bone.name)
        if reference:
            base_x, base_y = reference["scale"]
            scale = (scale[0] / base_x if base_x else 1.0,
                     scale[1] / base_y if base_y else 1.0)
        out[pose_bone.name] = {"pos": (head.x, head.y), "angle": frame_angle(source),
                               "scale": scale}
    return out


def sprite_bone_angles(arm, pairs: dict) -> dict:
    """Angle (degrees) between each sprite frame and its bone, at rest."""
    out = {}
    for name, plane in pairs.items():
        bone_matrix = arm.matrix_world @ arm.pose.bones[name].matrix
        delta = frame_angle(plane.matrix_world) - frame_angle(bone_matrix)
        out[name] = (delta + 180.0) % 360.0 - 180.0
    return out


def snap(value: float, scale: float, limit: float = 32767.0) -> float:
    """Puts a value on the grid of the binary format (i16, tenths, 1/10000)."""
    return max(-limit, min(limit, round(value * scale) / scale))


def snap_pose(delta) -> tuple:
    """A full pose `(dx, dy, rot, sx, sy)` snapped to the wire grid.

    Snapping here (and not only in `iska_pack.py`) keeps a re-bake idempotent: what
    comes out of Blender is already what the binary would store.
    """
    dx, dy, rot, sx, sy = delta
    return (snap(dx, 1.0), snap(dy, 1.0), snap(rot, iska.ANGLE_SCALE),
            snap(sx, iska.FIXED_SCALE), snap(sy, iska.FIXED_SCALE))


def bake_pose(skeleton, rig: dict, measured: dict, resting: dict) -> dict:
    """Engine deltas `{bone: (dx, dy, rot, sx, sy)}` from the measured world state.

    The engine composes a pose like this (`Skeleton.resolve_bones`, docs/FORMAT.md):

        pos_b   = pos_parent + R(angle_parent) * (scale_parent (.) (rest_b + d_b))
        angle_b = angle_parent + angle_b_rest + d_rot_b

    which inverts into, reading the parent's state where it *is* now (measured):

        rest_b + d_b = scale_parent^-1 (.) R(-angle_parent) * (pos_b - pos_parent)
        d_rot_b      = (angle_b - angle_b_rest) - (angle_parent - angle_parent_rest)

    The parent's absolute angle is the cumulative rest angle of the rig plus the
    rotation measured since the rest pose -- that is why `resting` (the same
    measurements taken at rest) is needed.
    """
    rest_angles = rest_world_angles(skeleton)
    out = {}
    for bone in skeleton.bones:
        name = bone["name"]
        here = measured[name]
        x, y = blender_to_stage(rig, *here["pos"])
        turned = here["angle"] - resting[name]["angle"]
        parent = bone["parent"]
        if parent is None:
            dx, dy, drot = x - bone["rest"][0], y - bone["rest"][1], turned
        else:
            there = measured[parent]
            px, py = blender_to_stage(rig, *there["pos"])
            parent_turn = there["angle"] - resting[parent]["angle"]
            angle = RAD(rest_angles[parent] + parent_turn)
            cosine, sine = math.cos(angle), math.sin(angle)
            vx, vy = x - px, y - py
            scale_x, scale_y = there["scale"]
            dx = (vx * cosine + vy * sine) / (scale_x or 1.0) - bone["rest"][0]
            dy = (-vx * sine + vy * cosine) / (scale_y or 1.0) - bone["rest"][1]
            drot = turned - parent_turn
        out[name] = snap_pose((dx, dy, drot, here["scale"][0], here["scale"][1]))
    return out


def apply_pose(arm, skeleton, rig: dict, pose, update) -> None:
    """Drives the pose bones so that Blender shows what the engine computes.

    The world matrix of each bone is rebuilt from `resolve_bones` (position, angle,
    scale) and assigned to `pose_bone.matrix` -- parents first, with an update in
    between, the reliable way to drive a hierarchy from world transforms. The scale
    goes along the **bone's** axes (module docstring).

    The bone's own Z is kept: it carries the draw order of the part it holds
    (`tools/rig_build.py` reads it from the planes), so the bound planes keep the
    stacking the engine draws them in instead of ending up coplanar in the viewport
    (z-fighting, one plane hiding another). Nothing else reads that Z: the bake
    measures x/y/angle/scale only, and the .iska never stores a Z.
    """
    from mathutils import Matrix, Vector          # provided by Blender

    rest_angles = rest_world_angles(skeleton)
    for i, bone in enumerate(skeleton.bones):
        x, y, angle, scale = skeleton.resolve_bones(pose)[i]
        pose_bone = arm.pose.bones[bone["name"]]
        bx, by = stage_to_blender(rig, x, y)
        turn = Matrix.Rotation(RAD(-(angle - rest_angles[bone["name"]])), 4, "Z")
        rest = pose_bone.bone.matrix_local.to_3x3().to_4x4()
        stretch = Matrix.Diagonal((scale[0], scale[1], 1.0, 1.0))
        pose_bone.matrix = (Matrix.Translation(Vector((bx, by,
                                                       pose_bone.bone.head_local.z)))
                            @ turn @ rest @ stretch)
        update()


def load_json(path: str) -> dict:
    import json
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: str, data: dict) -> None:
    import json
    import os
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
