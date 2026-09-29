"""Rend des images d'une animation .iska (sans Blender, sans SDL).

    python tools/iska_preview.py assets/rabbit3.iska --anim idle_loop \
        --frames 8 --out build/rabbit3/preview_idle.png
    python tools/iska_preview.py assets/rabbit3.iska --anim peek \
        --at 0,240,330,520,900,1400,1880,2060,2380,2700 \
        --out build/rabbit3/preview_peek.png --scale 1

Le rendu utilise exactement le meme blitter que le runtime C++
(`iska_common.blit_part`), et lit le binaire : ce que vous voyez ici est ce que
le moteur affichera (aux differences d'arrondi de RGB565 pres, qui n'existent pas
puisque l'asset est deja en RGB565).

`--frames N` repartit N images sur la duree ; `--at` impose les instants (ms).
"""
from __future__ import annotations

import argparse
import os

from PIL import Image, ImageDraw

import iska_common as iska


def render(data: dict, name: str, t_ms: float):
    """Framebuffer RGB565 de l'animation `name` a l'instant `t_ms`."""
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
    ap.add_argument("--anim", default=None, help="animation a rendre (defaut : la premiere)")
    ap.add_argument("--frames", type=int, default=8, help="nombre d'images reparties")
    ap.add_argument("--at", default=None, help="instants en ms separes par des virgules")
    ap.add_argument("--out", required=True, help="PNG de sortie (planche contact)")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--columns", type=int, default=0, help="colonnes (0 = automatique)")
    ap.add_argument("--dump-dir", default=None, help="ecrire aussi chaque image")
    args = ap.parse_args()

    with open(args.iska, "rb") as fh:
        data = iska.parse_iska(fh.read())
    name = args.anim or next(iter(data["anims"]))
    if name not in data["anims"]:
        raise SystemExit(f"animation inconnue : {name} "
                         f"(disponibles : {', '.join(data['anims'])})")
    anim = data["anims"][name]

    if args.at:
        times = [float(v) for v in args.at.split(",") if v.strip()]
    else:
        count = max(1, args.frames)
        times = [anim["duration"] * i / max(1, count - 1 if not anim["loop"] else count)
                 for i in range(count)]

    width, height = data["stage"]
    scale = max(1, args.scale)
    columns = args.columns or min(4, len(times)) or 1
    rows = (len(times) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * width * scale, rows * height * scale),
                      (10, 10, 14))
    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate(times):
        buf = render(data, name, t)
        tile = to_image(buf, width, height).resize((width * scale, height * scale),
                                                   Image.NEAREST)
        cx = (i % columns) * width * scale
        cy = (i // columns) * height * scale
        sheet.paste(tile, (cx, cy))
        draw.text((cx + 4, cy + 4), f"{name} t={t:.0f} ms", fill=(255, 240, 120))
        draw.rectangle([cx, cy, cx + width * scale - 1, cy + height * scale - 1],
                       outline=(60, 60, 70))
        if args.dump_dir:
            os.makedirs(args.dump_dir, exist_ok=True)
            tile.save(os.path.join(args.dump_dir, f"{name}_{int(round(t)):05d}.png"))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    sheet.save(args.out)
    print(f"[preview] {len(times)} images de {name} -> {args.out} "
          f"({sheet.size[0]}x{sheet.size[1]})")
    print(f"[preview] instants : {', '.join(f'{t:.0f}' for t in times)} ms")


if __name__ == "__main__":
    main()