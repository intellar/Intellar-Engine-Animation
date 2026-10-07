"""Reads the actions of a .blend back into the animations JSON.

    blender -b tools/source/rabbit3_anim.blend --python tools/blender_bake_anims.py -- \
        --rig tools/rigs/rabbit3.json --out tools/animations/rabbit3.json

The reverse of `tools/blender_import_anims.py`: every action of the .blend is
sampled **frame by frame** (1 frame = 10 ms), the world position, angle and scale of
each bone are measured on the bound planes, and the deltas the engine expects
(`dx, dy, rot, sx, sy` per bone) are recomputed from them -- the exact inverse of
what the importer wrote, so a round trip comes back to where it started
(`tools/anim_roundtrip.py` proves it on the asset itself).

Two things keep the result small and stable:

* **sparse keys**: a key is dropped as soon as the linear interpolation between its
  neighbours reproduces every frame it covers within `--tolerance` (half a wire
  step by default, so pruning cannot change a single stored value). A bone that
  never leaves the rest pose is not written at all;
* **snapped values**: `dx/dy` in whole pixels, `rot` in tenths of a degree,
  `sx/sy` in 1/10000, i.e. exactly what the binary will store -- re-baking the same
  .blend gives the same file, and `tools/iska_pack.py` reports no rounding.

`iska_loop` / `iska_duration_ms` (written by the importer) are carried over; without
them the action's own frame range sets the duration.
"""
from __future__ import annotations

import argparse
import os
import sys

import bpy                                   # noqa: E402  (provided by Blender)
from mathutils import Matrix                 # noqa: E402

FRAME_MS = 10.0                              # 100 fps: one frame = 10 ms
# One **wire step** -- a whole pixel, a tenth of a degree, 1/10000 of scale -- is
# the tolerance of the pruning: below that, a value that sits exactly on a rounding
# boundary flips between two levels from one frame to the next, and every flip would
# have to be written. One step is also the smallest difference the panel can show.
TOLERANCE = (1.0, 1.0, 0.1, 0.0001, 0.0001)
COMPONENTS = ("dx", "dy", "rot", "sx", "sy")
REST = (0.0, 0.0, 0.0, 1.0, 1.0)


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


def clear_pose(arm) -> None:
    """Everything to rest: the reference the deltas are measured from."""
    for pose_bone in arm.pose.bones:
        pose_bone.matrix_basis = Matrix.Identity(4)
    update()


def frames_of(action) -> list:
    start, end = action.frame_range
    return list(range(int(round(start)), int(round(end)) + 1))


def sample_action(arm, action, pairs, skeleton, rig, resting) -> list:
    """`[(t_ms, {bone: (dx, dy, rot, sx, sy)})]`, one entry per frame."""
    arm.animation_data.action = action
    samples = []
    for frame in frames_of(action):
        bpy.context.scene.frame_set(frame)
        update()
        measured = biska.measure(arm, pairs, resting)
        samples.append(((frame - 1) * FRAME_MS,
                        biska.bake_pose(skeleton, rig, measured, resting)))
    return samples


def fits(times, values, first: int, last: int, tolerance: float) -> bool:
    """Does the segment (first, last) stay within `tolerance` on every point?"""
    span = times[last] - times[first]
    if span <= 0:
        return True
    base = values[first]
    slope = (values[last] - base) / span
    for index in range(first + 1, last):
        if abs(base + slope * (times[index] - times[first]) - values[index]) > tolerance:
            return False
    return True


def pruned_indices(times, values, tolerance: float) -> list:
    """Greedy linear fit: keeps the fewest keys that stay within `tolerance`."""
    kept = [0]
    last = 0
    count = len(times)
    while last < count - 1:
        candidate = count - 1
        while candidate > last + 1 and not fits(times, values, last, candidate, tolerance):
            candidate -= 1
        kept.append(candidate)
        last = candidate
    return kept


def active_bones(samples, skeleton, tolerance) -> list:
    """`[(bone name, [(component, values over the frames)])]` that need keys."""
    active = []
    for bone in skeleton.bones:
        channels = []
        for component in range(5):
            channel = [pose[bone["name"]][component] for _t, pose in samples]
            if max(abs(value - REST[component]) for value in channel) \
                    > tolerance[component] * 0.5:
                channels.append((component, channel))
        if channels:
            active.append((bone["name"], channels))
    return active


def build_keys(samples, active, kept) -> list:
    """The sparse keys for a given set of kept frames.

    A bone is written in a key only when its value **changes** since its last
    written value: that is the carry rule of the format (`iska_pack.carry_keys`), so
    written back explicitly -- `{}` puts a bone back to rest. Only the components
    that leave the rest pose are listed, like the hand-written animations do.
    """
    times = [t for t, _pose in samples]
    carried = {name: REST for name, _channels in active}
    keys = []
    for index in sorted(kept):
        pose = {}
        for name, _channels in active:
            values = samples[index][1][name]
            if values == carried[name]:
                continue                     # the engine keeps the previous value
            pose[name] = {COMPONENTS[component]: values[component]
                          for component in range(5)
                          if abs(values[component] - REST[component]) > 1e-9}
            carried[name] = values
        keys.append({"t": int(round(times[index])), "pose": pose})
    return keys


def check(skeleton, keys, loop: bool, duration: int, samples, tolerance) -> tuple:
    """`(frames out of tolerance, worst |error| per component)`.

    Read back through the runtime's own interpolation (`iska.sample_pose`), which is
    the only judgement that matters: this is what the engine will display.
    """
    full = iska.carry_keys(skeleton, keys)
    clip = {"name": "check", "keys": full, "loop": loop, "duration": duration}
    bad = set()
    worst = [0.0] * 5
    for position, (t_ms, pose) in enumerate(samples):
        back = iska.sample_pose(clip, iska.anim_time(clip, t_ms))
        for index, bone in enumerate(skeleton.bones):
            for component in range(5):
                error = abs(back[index][component] - pose[bone["name"]][component])
                worst[component] = max(worst[component], error)
                if error > tolerance[component]:
                    bad.add(position)
    return bad, worst


def sparse_keys(samples, skeleton, tolerance, loop: bool, duration: int) -> tuple:
    """The keys to write: greedy linear fit, then verified and refined.

    Each channel is first pruned on its own (a key is dropped while the segment
    between its neighbours stays within `tolerance`), but the frames kept by one
    channel change the interpolation of the others, so the result is measured
    through the runtime and any frame left out of tolerance is put back. The loop
    converges in a couple of rounds and guarantees the printed error.
    """
    times = [t for t, _pose in samples]
    active = active_bones(samples, skeleton, tolerance)
    kept = {0, len(samples) - 1}
    counts = {}
    for name, channels in active:
        for component, channel in channels:
            indices = pruned_indices(times, channel, tolerance[component])
            kept.update(indices)
            counts[f"{name}.{COMPONENTS[component]}"] = len(indices)

    keys = build_keys(samples, active, kept)
    for _round in range(8):
        bad, _worst = check(skeleton, keys, loop, duration, samples, tolerance)
        if not bad:
            break
        for index in bad:
            kept.update({max(0, index - 1), index, min(len(samples) - 1, index + 1)})
        keys = build_keys(samples, active, kept)
    return keys, counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rig", default=os.path.join("tools", "rigs", "rabbit3.json"))
    ap.add_argument("--out", default=os.path.join("tools", "animations", "rabbit3.json"))
    ap.add_argument("--tolerance", type=float, default=1.0,
                    help="scale of the default tolerance (1 = half a wire step)")
    ap.add_argument("--dense", action="store_true",
                    help="keep one key per frame (no pruning)")
    ap.add_argument("--only", default="",
                    help="comma-separated action names to bake (the other animations "
                         "already in the JSON are kept)")
    args = ap.parse_args(argv_after_dashdash())
    out = resolve(args.out)

    arm = armature()
    if arm is None:
        raise SystemExit("[bake_anims] no armature in this .blend")
    if arm.animation_data is None or not arm.animation_data.action:
        pass                              # actions may exist without being assigned
    pairs = biska.bound_parts(arm)
    if not pairs:
        print("[bake_anims] WARNING: no plane is bound to the armature: the measured "
              "poses will be the bone transforms alone (run tools/blender_bind.py)")
    rig = biska.load_json(resolve(args.rig))
    skeleton = iska.Skeleton(rig)

    tolerance = tuple(value * args.tolerance for value in TOLERANCE)

    # the rest pose is the reference of every delta: measure it before anything else
    if arm.animation_data is not None:
        arm.animation_data.action = None
    clear_pose(arm)
    resting = biska.measure(arm, pairs)

    wanted = [name.strip() for name in args.only.split(",") if name.strip()]
    actions = [action for action in bpy.data.actions if not wanted or action.name in wanted]
    actions.sort(key=lambda action: (action.get("iska_order", 1000), action.name))
    if not actions:
        raise SystemExit("[bake_anims] no action in this .blend: import the "
                         "animations first (tools/blender_import_anims.py)")

    # metadata of the file being rewritten (`character`, `rig`, `notes`...) is kept.
    # With `--only`, only the selected animations are rewritten: the others already in
    # the JSON are kept as they are, so baking one animation does not drop the rest.
    document = {}
    if os.path.isfile(out):
        document = biska.load_json(out)
    existing = document.get("animations", {})
    if wanted:
        document["animations"] = {name: anim for name, anim in existing.items()
                                  if name not in wanted}
    else:
        document["animations"] = {}

    print(f"[bake_anims] {len(actions)} action(s) -> {out}")
    for action in actions:
        name = action.name
        samples = sample_action(arm, action, pairs, skeleton, rig, resting)
        loop = bool(action.get("iska_loop", False))
        duration = int(action.get("iska_duration_ms", samples[-1][0]))
        if args.dense:
            keys = [{"t": int(round(t)),
                     "pose": {bone["name"]: {COMPONENTS[i]: value for i, value in
                                             enumerate(pose[bone["name"]])
                                             if abs(value - REST[i]) > 1e-9}
                              for bone in skeleton.bones
                              if pose[bone["name"]] != REST}}
                    for t, pose in samples]
            counts = {}
        else:
            keys, counts = sparse_keys(samples, skeleton, tolerance, loop, duration)
        _bad, error = check(skeleton, keys, loop, duration, samples, tolerance)
        document["animations"][name] = {"loop": loop, "duration": duration, "keys": keys}
        print(f"[bake_anims]   {name:12s} {duration:5d} ms, loop={str(loop):5s}, "
              f"{len(samples)} frames -> {len(keys)} keys, "
              f"max error dx={error[0]:.3f} dy={error[1]:.3f} rot={error[2]:.3f} "
              f"sx={error[3]:.5f} sy={error[4]:.5f}")
        if counts:
            busiest = sorted(counts.items(), key=lambda item: -item[1])[:3]
            print(f"[bake_anims]     channels needing the most keys: "
                  + ", ".join(f"{name_}={count}" for name_, count in busiest))

    biska.save_json(out, document)
    print(f"[bake_anims] {len(document['animations'])} animation(s) -> "
          f"{os.path.abspath(out)}")
    print("[bake_anims] rebuild the asset: python tools/build_asset.py")


main()
