"""Renders an animation of an .iska to an animated GIF (no Blender, no SDL).

    python tools/iska_gif.py assets/rabbit3.iska --anim idle_loop \\
        --step 80 --scale 2 --out docs/img/rabbit3_idle.gif

Frames are drawn by the same blitter as the runtime (`iska_common`), so the GIF shows
exactly what the engine displays. A looping animation produces a seamless GIF
(`loop=0`): pick a `--step` that divides the duration for a clean wrap.
"""
from __future__ import annotations

import argparse
import os

from PIL import Image

import iska_common as iska


def render(data: dict, name: str, t_ms: float):
    """RGB565 framebuffer of animation `name` at time `t_ms`."""
    anim = data["anims"][name]
    skeleton = iska.skeleton_from_iska(data)
    buf = iska.new_frame(data["stage"][0], data["stage"][1], iska.rgb_to_565(16, 17, 22))
    skeleton.draw(buf, iska.sample_pose(anim, iska.anim_time(anim, t_ms)),
                  iska.sprites_from_iska(data, skeleton))
    return buf


def to_image(buf, width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        row = y * width
        for x in range(width):
            px[x, y] = iska.rgb565_to_rgb(buf[row + x])
    return img


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("iska")
    ap.add_argument("--anim", default=None, help="animation to render (default: the first)")
    ap.add_argument("--step", type=int, default=80, help="ms between frames")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--out", required=True, help="output .gif")
    args = ap.parse_args()

    with open(args.iska, "rb") as fh:
        data = iska.parse_iska(fh.read())
    name = args.anim or next(iter(data["anims"]))
    if name not in data["anims"]:
        raise SystemExit(f"unknown animation: {name} "
                         f"(available: {', '.join(data['anims'])})")
    anim = data["anims"][name]

    width, height = data["stage"]
    scale = max(1, args.scale)

    frames = []
    for t in range(0, anim["duration"], args.step):
        img = to_image(render(data, name, t), width, height)
        if scale != 1:
            img = img.resize((width * scale, height * scale), Image.NEAREST)
        frames.append(img)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    frames[0].save(args.out, save_all=True, append_images=frames[1:],
                   duration=args.step, loop=0, optimize=True)
    print(f"[gif] {len(frames)} frames of {name} ({anim['duration']} ms) -> {args.out} "
          f"({width * scale}x{height * scale}, {args.step} ms/frame)")


if __name__ == "__main__":
    main()
