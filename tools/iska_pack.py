"""Empaquette un rig + des animations en `.iska`, le fichier lu par le moteur.

    python tools/iska_pack.py --rig tools/rigs/rabbit3.json \
        --anims tools/animations/rabbit3.json --out assets/rabbit3.iska

C'est l'etape qui transforme les PNG et les poses ecrites a la main en un binaire
autonome, sans dependance a Blender ni a Pillow cote moteur :

  * chaque PNG est mis a l'echelle de sa case sprite (`rig.parts[].sprite`),
    converti en RGB565, et les pixels translucides deviennent **magenta**
    (cle de transparence du format) ;
  * les cases sont concatenees dans un seul bloc de pixels (offset en octets) ;
  * les poses nommees du JSON d'animations (`{"armL": {"rot": -30}}`) sont
    completees en poses plein format (un quintuplet par os, dans l'ordre du rig)
    et validees : nom d'os inconnu, cles non croissantes, duree incoherente...

`--check` valide tout sans rien ecrire (utile en pre-commit / CI).
"""
from __future__ import annotations

import argparse
import array
import json
import os

from PIL import Image

import iska_common as iska


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check_anim(skeleton: iska.Skeleton, name: str, anim: dict) -> list:
    """Valide une animation et renvoie ses cles en poses plein format.

    **Une cle ne decrit que ce qui bouge** : un os absent d'une cle conserve la
    valeur de la cle precedente (comme un canal d'animation sparse), et citer un
    os sans preciser une composante remet cette composante au repos. Pour
    renvoyer un os au repos, on l'ecrit donc explicitement (`"armL": {}`).
    """
    if "keys" not in anim or len(anim["keys"]) < 2:
        raise SystemExit(f"{name} : au moins deux cles sont necessaires")
    last_t = None
    for key in anim["keys"]:
        t = int(round(key["t"]))
        if last_t is not None and t <= last_t:
            raise SystemExit(f"{name} : les temps de cle doivent etre croissants "
                             f"({last_t} puis {t})")
        last_t = t
    try:
        keys = iska.carry_keys(skeleton, anim["keys"])
    except KeyError as exc:
        raise SystemExit(f"{name} : {exc.args[0]}") from None
    duration = int(round(anim.get("duration", last_t)))
    if duration < last_t:
        raise SystemExit(f"{name} : duree {duration} ms inferieure a la derniere cle {last_t}")
    if anim.get("loop") and keys[0][0] != 0:
        raise SystemExit(f"{name} : une animation en boucle doit commencer a t=0")
    return keys, duration


def build_sprites(rig: dict, base_dir: str, alpha_threshold: int):
    """Bloc pixels (array('H')) + records de parts, dans l'ordre de dessin."""
    parts = sorted(rig["parts"], key=lambda p: p["draw_order"])
    bone_index = {b["name"]: i for i, b in enumerate(rig["bones"])}
    pixels = array.array("H")
    records = []
    report = []
    for part in parts:
        path = os.path.join(base_dir, part["image"])
        if not os.path.exists(path):
            raise SystemExit(f"PNG introuvable : {path}")
        with Image.open(path) as img:
            sw, sh = part["sprite"]
            sprite = iska.image_to_sprite(img, (sw, sh), alpha_threshold)
        offset = len(pixels) * 2
        pixels.extend(sprite)
        records.append({
            "bone": bone_index.get(part["bone"], -1),
            "pivot": (part["pivot"][0], part["pivot"][1]),
            "sprite": (sw, sh),
            "draw_order": part["draw_order"],
            "flags": 0,
            "pixel_offset": offset,
            "pixel_bytes": sw * sh * 2,
        })
        report.append((part["name"], sw, sh, sw * sh * 2))
    return pixels, records, report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rig", required=True, help="JSON de rig (tools/rig_build.py)")
    ap.add_argument("--anims", required=True, help="JSON d'animations")
    ap.add_argument("--out", required=True, help="fichier .iska a ecrire")
    ap.add_argument("--alpha-threshold", type=int, default=128,
                    help="alpha en dessous duquel le pixel devient transparent (magenta)")
    ap.add_argument("--check", action="store_true",
                    help="valider sans ecrire le .iska")
    args = ap.parse_args()

    rig = load_json(args.rig)
    anims_doc = load_json(args.anims)
    skeleton = iska.Skeleton(rig)

    if not skeleton.bones:
        raise SystemExit("rig sans os")
    for i, bone in enumerate(skeleton.bones):
        parent = bone["parent"]
        if parent is not None and skeleton.index[parent] >= i:
            raise SystemExit(f"rig : l'os {bone['name']} doit venir apres son parent "
                             "(invariant du format ISKA)")

    animations = []
    for name, anim in anims_doc["animations"].items():
        keys, duration = check_anim(skeleton, name, anim)
        animations.append({"name": name, "loop": bool(anim.get("loop")),
                           "duration_ms": duration, "keys": keys})

    base_dir = os.path.dirname(os.path.abspath(args.rig))
    pixels, records, report = build_sprites(rig, base_dir, args.alpha_threshold)

    bones = [{"parent": None if b["parent"] is None else skeleton.index[b["parent"]],
              "rest": (b["rest"][0], b["rest"][1]), "angle": b["angle"]}
             for b in skeleton.bones]

    blob = iska.build_iska(rig["stage"]["w"], rig["stage"]["h"], bones, records,
                           animations, pixels)

    print(f"[iska_pack] {len(bones)} os, {len(records)} parts, "
          f"{len(animations)} animations")
    for name, sw, sh, byte_count in report:
        print(f"[iska_pack]   part {name:6s} {sw:3d}x{sh:<3d} {byte_count:6d} o")
    for anim in animations:
        print(f"[iska_pack]   anim {anim['name']:10s} duree={anim['duration_ms']:5d} ms "
              f"boucle={str(anim['loop']):5s} cles={len(anim['keys'])}")
    print(f"[iska_pack] bloc pixels : {len(pixels) * 2} o, fichier : {len(blob)} o")

    if args.check:
        print("[iska_pack] --check : rien ecrit (validation OK)")
        return

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(blob)
    print(f"[iska_pack] -> {out_path}")

    # relecture de controle : le fichier doit se relire a l'identique
    check = iska.parse_iska(blob)
    assert check["stage"] == [rig["stage"]["w"], rig["stage"]["h"]]
    assert len(check["parts"]) == len(records)
    assert set(check["anims"]) == {a["name"] for a in animations}
    for anim in animations:
        assert len(check["anims"][anim["name"]]["keys"]) == len(anim["keys"])
    print("[iska_pack] relecture du binaire : OK")


if __name__ == "__main__":
    main()

