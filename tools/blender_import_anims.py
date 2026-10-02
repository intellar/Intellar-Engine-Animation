"""Puts the animations of a JSON file into a bound .blend, as Blender actions.

    blender -b tools/source/rabbit3_anim.blend --python tools/blender_import_anims.py -- \
        --anims tools/animations/rabbit3.json --out tools/source/rabbit3_anim.blend

One action per animation, with a key **at every time the JSON itself keys** (the
scene runs at 100 fps: 1 frame = 10 ms, and those times land on whole frames),
LINEAR interpolation, and the position, angle and scale of every bone taken from
the engine's own maths (`iska_common.Skeleton.resolve_bones`) rather than converted
by hand.

The runtime plays a clip by interpolating **linearly between those very poses** and
nothing else, so a key here is a key there: the Dope Sheet holds one column per
stored pose (`idle_loop` comes out as 28 columns, not 241), editing a curve is
editing the animation, and what you scrub is exactly what the panel draws
(`tools/anim_roundtrip.py` keeps proving it). `--dense` writes a key per 10 ms frame
instead -- the same motion to the eye, but a wall of keys that can neither be told
apart nor dragged apart.

Each action also carries `iska_loop` and `iska_duration_ms`, so
`tools/blender_bake_anims.py` can write back a JSON that plays the same thing
(`tools/anim_roundtrip.py` checks that round trip).

The planes must be **bound** to the bones (`tools/blender_bind.py`): the keys are
put on the bones, so an unbound plane would simply not follow.
"""
from __future__ import annotations

import argparse
import os
import sys

import bpy                                   # noqa: E402  (provided by Blender)

FRAME_MS = 10.0                              # 100 fps: one frame = 10 ms


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


# The shared modules live next to this script; `__file__` cannot be trusted when
# Blender runs a Text block, hence the repository root found above.
sys.path.append(os.path.join(ROOT, "tools"))
import blender_iska as biska                 # noqa: E402
import iska_common as iska                   # noqa: E402


def update() -> None:
    bpy.context.view_layer.update()


def armature():
    return next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)


def check_binding(arm) -> None:
    """A key on a bone nobody follows is an animation nobody sees."""
    if not biska.bound_parts(arm):
        print("[import_anims] WARNING: no plane is bound to the armature: the "
              "animation will be invisible. Run tools/blender_bind.py first.")


def key_samples(keys, loop: bool, duration: int, dense: bool) -> list:
    """`[(frame, full pose)]`: one entry per key the action is going to hold.

    `keys` is what `iska_common.carry_keys` returns: the *full* pose at each time
    the JSON keys, which is all the runtime ever needs (it interpolates linearly
    between those poses and nothing else). Writing one Blender key per entry puts
    the Dope Sheet and the JSON on the same times -- one column per stored pose,
    which is what makes the action editable.

    `dense=True` writes one pose per 10 ms frame instead (frame 1 = t 0): the same
    curves to the eye, but no column left to grab -- kept for sculpting a curve
    from scratch, not for retouching one.
    """
    if not dense:
        return [(int(round(t_ms / FRAME_MS)) + 1, pose) for t_ms, pose in keys]
    clip = {"name": "sample", "keys": keys, "loop": loop, "duration": duration}
    count = int(round(duration / FRAME_MS)) + 1
    return [(index + 1, iska.sample_pose(clip, iska.anim_time(clip, index * FRAME_MS)))
            for index in range(count)]


def movers(skeleton, poses) -> list:
    """Bones that leave the rest pose: only those are keyed (readable curves)."""
    moving = []
    for index, bone in enumerate(skeleton.bones):
        for _frame, pose in poses:
            dx, dy, rot, sx, sy = pose[index]
            if (dx, dy, rot) != (0.0, 0.0, 0.0) or (sx, sy) != (1.0, 1.0):
                moving.append(bone["name"])
                break
    return moving


def key_bones(arm, names: list, frame: int) -> None:
    for name in names:
        pose_bone = arm.pose.bones[name]
        pose_bone.keyframe_insert("location", frame=frame)
        pose_bone.keyframe_insert("rotation_quaternion", frame=frame)
        pose_bone.keyframe_insert("scale", frame=frame)


def action_fcurves(action) -> list:
    """The F-curves of an action, wherever Blender keeps them.

    `action.fcurves` up to Blender 4.3; after that the action is *slotted* and the
    curves live in the channelbag of each layer (`Action.fcurves` was removed in
    5.x, where reading it raises `AttributeError`). Same accessor as the one in
    `tools/blender_export.py`.
    """
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        return list(legacy)
    out = []
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                out.extend(bag.fcurves)
    return out


def set_linear(action) -> None:
    """LINEAR on every key -- the runtime interpolates linearly.

    Harmless on a key per frame (the curve never gets room to bulge), essential on
    the sparse keys written here: a Bezier key would swing a bone past what the
    panel shows between two JSON poses. The interpolation is not left to whatever
    is set in the user's preferences.
    """
    for fcurve in action_fcurves(action):
        for point in fcurve.keyframe_points:
            point.interpolation = "LINEAR"
        fcurve.update()


def import_animation(arm, skeleton, rig: dict, name: str, anim: dict, order: int,
                     dense: bool) -> dict:
    """Builds the action of one animation; returns a one-line report."""
    loop = bool(anim.get("loop"))
    keys = iska.carry_keys(skeleton, anim["keys"])
    duration = int(round(anim.get("duration", keys[-1][0])))
    poses = key_samples(keys, loop, duration, dense)
    moving = movers(skeleton, poses)

    if arm.animation_data is None:
        arm.animation_data_create()
    arm.animation_data.action = None
    previous = bpy.data.actions.get(name)
    if previous is not None:                   # idempotent: re-importing replaces
        bpy.data.actions.remove(previous)
    action = bpy.data.actions.new(name)
    arm.animation_data.action = action

    for pose_bone in arm.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"
    for frame, pose in poses:
        biska.apply_pose(arm, skeleton, rig, pose, update)
        key_bones(arm, moving, frame)
    set_linear(action)                         # no bulge between the JSON poses

    action["iska_loop"] = loop
    action["iska_duration_ms"] = duration
    action["iska_order"] = order               # so a re-bake keeps the JSON order
    action["iska_keys_json"] = len(anim["keys"])
    action.use_fake_user = True                # keep it in the .blend even when it
    #                                            is not the action being played
    try:
        action.use_cyclic = loop               # only from Blender 4.4 on
    except Exception:
        pass
    return {"name": name, "loop": loop, "duration": duration, "poses": len(poses),
            "last_frame": max(frame for frame, _pose in poses), "dense": dense,
            "bones": moving, "keys_json": len(anim["keys"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anims", default=os.path.join("tools", "animations",
                                                    "rabbit3.json"))
    ap.add_argument("--rig", default=os.path.join("tools", "rigs", "rabbit3.json"))
    ap.add_argument("--out", default="", help=".blend to save (empty = don't save)")
    ap.add_argument("--dense", action="store_true",
                    help="one key per 10 ms frame instead of one per JSON key (a wall "
                         "of keys: kept for sculpting a curve from scratch)")
    args = ap.parse_args(argv_after_dashdash())

    arm = armature()
    if arm is None:
        raise SystemExit("[import_anims] no armature in this .blend")
    check_binding(arm)

    rig = biska.load_json(resolve(args.rig))
    document = biska.load_json(resolve(args.anims))
    skeleton = iska.Skeleton(rig)
    missing = [bone["name"] for bone in rig["bones"] if bone["name"] not in arm.pose.bones]
    if missing:
        raise SystemExit(f"[import_anims] the armature has no bone(s) {missing}: the "
                         f"rig and the .blend do not go together")

    try:            # keys must be linear: the runtime interpolates linearly
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    except Exception as exc:
        print(f"[import_anims] note: could not force the default interpolation "
              f"({exc}); check the curves are linear")

    print(f"[import_anims] {args.anims}: {len(document['animations'])} animation(s)")
    reports = []
    for order, (name, anim) in enumerate(document["animations"].items()):
        report = import_animation(arm, skeleton, rig, name, anim, order, args.dense)
        reports.append(report)
        where = "one per 10 ms frame" if report["dense"] \
            else "at the JSON's own times"
        print(f"[import_anims]   {name:12s} {report['duration']:5d} ms, "
              f"loop={str(report['loop']):5s} -> action with {report['poses']} key(s) "
              f"({where}), {report['keys_json']} JSON keys, "
              f"{len(report['bones'])} animated bone(s): "
              f"{', '.join(report['bones']) or '(none)'}")

    scene = bpy.context.scene
    scene.render.fps = 100
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = max(report["last_frame"] for report in reports) if reports else 1
    print(f"[import_anims] timeline: 100 fps, frames {scene.frame_start}.."
          f"{scene.frame_end} (1 frame = 10 ms)")
    print("[import_anims] scrub the Dope Sheet: one row per bone, one column per JSON "
          "key; move, add or re-curve them, then bake with "
          "tools/blender_bake_anims.py")

    if args.out:
        out_path = os.path.abspath(resolve(args.out))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out_path)
        print(f"[import_anims] {len(reports)} action(s) -> {out_path}")
    print("[import_anims] back to JSON: python tools/build_asset.py "
          "--anims-from-blender")


main()
