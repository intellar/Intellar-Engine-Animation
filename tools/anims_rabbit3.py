"""Ecrit les animations de rabbit3 (tools/animations/rabbit3.json).

    python tools/anims_rabbit3.py --rig tools/rigs/rabbit3.json \
        --out tools/animations/rabbit3.json

Les animations sont **ecrites ici, pas dans Blender** : les valeurs sont des
deltas par rapport a la pose de repos du rig, en pixels ecran et en degres
(positif = horaire). C'est volontaire -- le timing (un rebond de 90 ms, un
clignement de 80 ms) se regle beaucoup plus vite dans un tableau que dans une
timeline, et le resultat est versionnable et testable.

Deux animations sont produites :

* `idle_loop`  : respiration au repos, boucle parfaite (la pose a t=0 et celle a
  t=duree sont identiques), avec un clignement des yeux.
* `peek`       : one-shot -- le lapin est hors cadre, bondit dans le panneau,
  regarde a gauche puis a droite, fait un petit saut sur place, puis replonge.

Conventions des poses (dict nom d'os -> deltas) :

    dx, dy  : translation en pixels (dy positif = vers le bas de l'ecran)
    rot     : rotation en degres, horaire a l'ecran
    sx, sy  : echelle appliquee a la part (1.0 = taille normale) ; l'echelle
              n'est pas heritee par les os enfants (voir docs/FORMAT.md)

Un os absent d'une pose garde sa position de repos. Les cles sont triees par
temps croissant et les deltas de meme temps sont fusionnes.
"""
from __future__ import annotations

import argparse
import json
import math
import os

import iska_common as iska

TAU = 2.0 * math.pi


def merge(keys: dict, t: float, deltas: dict) -> None:
    """Ajoute une pose partielle a l'instant `t` (fusion par os)."""
    slot = keys.setdefault(int(round(t)), {})
    for bone, delta in deltas.items():
        slot.setdefault(bone, {}).update(delta)


def idle_loop() -> dict:
    """Respiration au repos + clignement : boucle de 2400 ms, sans couture.

    Les sinus ont une periode qui divise la duree (2400 ms et 1200 ms), donc la
    pose a t=2400 est rigoureusement identique a celle de t=0 : la boucle ne
    saute pas. Le clignement est pose a 1500 ms, a l'interieur de la boucle.

    Les cles du clignement sont ajoutees **a la grille de la respiration** : une
    cle qui ne parlerait que des yeux laisserait le corps repartir au repos le
    temps d'un clignement (le bug a ete attrape par la comparaison d'empreintes
    entre le moteur C++ et l'outillage Python).
    """
    duration = 2400
    blink = [(1440, 0.0), (1520, 0.92), (1600, 0.92), (1660, 0.0)]
    times = sorted(set(range(0, duration + 1, 100)) | {t for t, _ in blink})

    keys = {}
    for t in times:
        breath = math.sin(TAU * t / duration)          # 1 cycle : inspiration
        sway = math.sin(TAU * t / 1200.0)              # 2 cycles : balancement
        merge(keys, t, {
            # le torse porte la respiration : les pieds restent au sol
            "torso": {"dy": round(-2.6 * breath, 3),
                      "sx": round(1.0 + 0.022 * breath, 4),
                      "sy": round(1.0 - 0.038 * breath, 4)},
            "head": {"dy": round(-1.1 * math.sin(TAU * t / duration - 0.6), 3),
                     "rot": round(1.8 * math.sin(TAU * t / duration - 0.9), 2)},
            "earL": {"rot": round(4.6 * math.sin(TAU * t / duration - 1.2), 2)},
            "earR": {"rot": round(3.4 * math.sin(TAU * t / duration - 1.5), 2)},
            "armL": {"rot": round(2.6 * math.sin(TAU * t / duration - 1.7), 2)},
            "armR": {"rot": round(-2.6 * math.sin(TAU * t / duration - 1.7), 2)},
            "root": {"dx": round(1.3 * sway, 3)},
        })

    # clignement : les yeux s'ecrasent sur eux-memes (leur pivot est leur centre)
    for t, closed in blink:
        merge(keys, t, {"eyeL": {"sy": round(1.0 - closed, 4)},
                        "eyeR": {"sy": round(1.0 - closed, 4)}})

    ordered = [{"t": t, "pose": keys[t]} for t in sorted(keys)]
    return {"loop": True, "duration": duration, "keys": ordered}


def peek() -> dict:
    """One-shot de 2700 ms : hors cadre -> bond -> regards -> saut -> replonge.

    `below` sort le lapin sous le panneau : la part la plus haute (les oreilles)
    est a ~95 px du haut du panneau, il faut donc au moins 225 px pour qu'elle
    disparaisse. On prend 240 px de marge.
    """
    below = 240
    keys = {}

    def at(t, **bones):
        merge(keys, t, bones)

    # -- cache, puis anticipation -------------------------------------------
    at(0, root={"dy": below}, torso={"sy": 1.05, "sx": 0.97},
       earL={"rot": -22}, earR={"rot": 22}, head={"dy": 4},
       armL={"rot": 14}, armR={"rot": -14})
    at(120, root={"dy": below + 6}, torso={"sy": 1.08, "sx": 0.95},
       earL={"rot": -26}, earR={"rot": 26}, head={"dy": 6},
       armL={"rot": 18}, armR={"rot": -18})
    # -- jaillissement (etirement vertical) ---------------------------------
    at(240, root={"dy": 60}, torso={"sy": 1.12, "sx": 0.93},
       earL={"rot": -16}, earR={"rot": 16}, armL={"rot": 10}, armR={"rot": -10})
    at(330, root={"dy": -18}, torso={"sy": 1.07, "sx": 0.96},
       earL={"rot": -8}, earR={"rot": 8}, armL={"rot": 4}, armR={"rot": -4})
    at(430, root={"dy": 0}, torso={"sy": 1.0, "sx": 1.0},
       earL={"rot": 0}, earR={"rot": 0}, armL={"rot": 0}, armR={"rot": 0})
    # -- ecrasement a l'atterrissage ----------------------------------------
    at(520, root={"dy": 5}, torso={"sy": 0.92, "sx": 1.06},
       earL={"rot": 12}, earR={"rot": -12}, armL={"rot": -8}, armR={"rot": 8})
    at(640, root={"dy": 0}, torso={"sy": 1.0, "sx": 1.0},
       earL={"rot": 0}, earR={"rot": 0}, armL={"rot": 0}, armR={"rot": 0})

    # -- regard a gauche ----------------------------------------------------
    at(780, root={"dx": -12, "dy": 2}, torso={"rot": 4.0},
       head={"rot": -3.0}, eyeL={"dx": -1.8}, eyeR={"dx": -1.8},
       earL={"rot": -12}, earR={"rot": 8}, armL={"rot": -6}, armR={"rot": 6})
    at(980, root={"dx": -14, "dy": 2}, torso={"rot": 4.5},
       head={"rot": -2.0}, eyeL={"dx": -2.0}, eyeR={"dx": -2.0},
       earL={"rot": -8}, earR={"rot": 10})
    # -- regard a droite (passage rapide au centre) -------------------------
    at(1080, root={"dx": 0, "dy": 0}, torso={"rot": 0.0}, head={"rot": 0.0},
       eyeL={"dx": 0.0}, eyeR={"dx": 0.0}, earL={"rot": 4}, earR={"rot": -4})
    at(1180, root={"dx": 12, "dy": 2}, torso={"rot": -4.0},
       head={"rot": 3.0}, eyeL={"dx": 2.0}, eyeR={"dx": 2.0},
       earL={"rot": 10}, earR={"rot": -12}, armL={"rot": 6}, armR={"rot": -6})
    at(1400, root={"dx": 14, "dy": 2}, torso={"rot": -4.5},
       head={"rot": 2.0}, eyeL={"dx": 2.2}, eyeR={"dx": 2.2},
       earL={"rot": 8}, earR={"rot": -8})
    at(1600, root={"dx": 0, "dy": 0}, torso={"rot": 0.0}, head={"rot": 0.0},
       eyeL={"dx": 0.0}, eyeR={"dx": 0.0}, earL={"rot": 0}, earR={"rot": 0},
       armL={"rot": 0}, armR={"rot": 0})

    # -- petit saut sur place ----------------------------------------------
    at(1760, root={"dy": 9}, torso={"sy": 0.93, "sx": 1.05},
       earL={"rot": 10}, earR={"rot": -10}, armL={"rot": -10}, armR={"rot": 10})
    at(1880, root={"dy": -32}, torso={"sy": 1.07, "sx": 0.96},
       footL={"dy": -9}, footR={"dy": -9},
       earL={"rot": -16}, earR={"rot": 16}, armL={"rot": 16}, armR={"rot": -16})
    at(1990, root={"dy": -8}, torso={"sy": 1.0, "sx": 1.0},
       footL={"dy": -3}, footR={"dy": -3}, earL={"rot": -6}, earR={"rot": 6})
    at(2060, root={"dy": 4}, torso={"sy": 0.90, "sx": 1.07},
       footL={"dy": 0}, footR={"dy": 0},
       earL={"rot": 14}, earR={"rot": -14}, armL={"rot": -6}, armR={"rot": 6})
    at(2200, root={"dy": 0}, torso={"sy": 1.0, "sx": 1.0},
       earL={"rot": 0}, earR={"rot": 0}, armL={"rot": 0}, armR={"rot": 0})

    # -- replongeon ---------------------------------------------------------
    at(2380, root={"dy": 96}, torso={"sy": 1.04, "sx": 0.98},
       earL={"rot": -16}, earR={"rot": 16}, armL={"rot": 12}, armR={"rot": -12})
    at(2700, root={"dy": below}, torso={"sy": 1.0, "sx": 1.0},
       earL={"rot": -6}, earR={"rot": 6}, armL={"rot": 0}, armR={"rot": 0})

    ordered = [{"t": t, "pose": keys[t]} for t in sorted(keys)]
    return {"loop": False, "duration": 2700, "keys": ordered}


def validate(skeleton: iska.Skeleton, name: str, anim: dict) -> None:
    """Verifie les noms d'os, l'ordre des temps et le raccord de la boucle.

    La boucle est verifiee apres application de la regle de report des os
    (`iska_common.carry_keys`) : c'est exactement la pose que le moteur jouera.
    """
    last_t = None
    for key in anim["keys"]:
        if last_t is not None and key["t"] <= last_t:
            raise SystemExit(f"{name} : t={key['t']} apres t={last_t}")
        last_t = key["t"]
    try:
        poses = iska.carry_keys(skeleton, anim["keys"])
    except KeyError as exc:
        raise SystemExit(f"{name} : {exc.args[0]}") from None
    if anim["loop"] and poses[0][1] != poses[-1][1]:
        raise SystemExit(f"{name} : boucle non raccordee (la pose a t=0 et celle "
                         f"a t={last_t} different)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rig", default="tools/rigs/rabbit3.json")
    ap.add_argument("--out", default="tools/animations/rabbit3.json")
    args = ap.parse_args()

    with open(args.rig, encoding="utf-8") as fh:
        rig = json.load(fh)
    skeleton = iska.Skeleton(rig)

    animations = {"idle_loop": idle_loop(), "peek": peek()}
    for name, anim in animations.items():
        validate(skeleton, name, anim)

    doc = {
        "character": rig.get("id", "rabbit3"),
        "rig": os.path.relpath(os.path.abspath(args.rig),
                               os.path.dirname(os.path.abspath(args.out))).replace("\\", "/"),
        "notes": ["dx/dy en pixels ecran (dy vers le bas), rot en degres horaires,",
                  "sx/sy = echelle de la part (non heritee par les enfants)."],
        "animations": animations,
    }

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"[anims] {len(animations)} animations -> {out_path} ; rig {args.rig}")
    for name, anim in animations.items():
        spans = {"dx": 0.0, "dy": 0.0, "rot": 0.0, "scale": 1.0}
        for key in anim["keys"]:
            for delta in key["pose"].values():
                spans["dx"] = max(spans["dx"], abs(delta.get("dx", 0.0)))
                spans["dy"] = max(spans["dy"], abs(delta.get("dy", 0.0)))
                spans["rot"] = max(spans["rot"], abs(delta.get("rot", 0.0)))
                for axis in ("sx", "sy"):
                    spans["scale"] = max(spans["scale"],
                                         abs(delta.get(axis, 1.0) - 1.0) + 1.0)
        print(f"[anims]   {name:10s} duree={anim['duration']:5d} ms "
              f"boucle={str(anim['loop']):5s} cles={len(anim['keys']):3d} "
              f"|dx|<={spans['dx']:.0f} |dy|<={spans['dy']:.0f} "
              f"|rot|<={spans['rot']:.1f} echelle<={spans['scale']:.2f}")


if __name__ == "__main__":
    main()



