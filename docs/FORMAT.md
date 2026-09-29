# Format ISKA v1

Un `.iska` est un fichier **autonome** : squelette, boîtes de sprites RGB565 et
animations. Le moteur n'a besoin que de ce fichier pour animer un personnage —
ni Blender, ni PNG, ni parseur JSON.

Deux implémentations existent, volontairement identiques :

* `src/Iska/` — C++17, aucune dépendance (l'écran SDL est optionnel) ;
* `tools/iska_common.py` — Python, utilisé par le packer et les outils de
  vérification. `tools/iska_clip_check.py` compare les deux rendus **au pixel
  près** (94 images identiques sur les deux animations de `rabbit3`).

## Conventions

* **Petit-boutiste** partout, champs non signés sauf mention `i`.
* Coordonnées en **pixels écran** : X vers la droite, Y vers le **bas**.
* Angles en **dixièmes de degré**, **positif = horaire** à l'écran, `0` = sprite
  non tourné.
* Un pixel **magenta** (`RGB565 = 0xF81F`) est la **clé de transparence** : il
  n'est jamais écrit. Le packer transforme les pixels d'alpha < `--alpha-threshold`
  (128 par défaut) en magenta.

## En-tête (32 octets)

| Octet | Type | Champ |
| ---: | :--- | :--- |
| 0 | `char[4]` | `"ISKA"` |
| 4 | `u16` | version (1) |
| 6 | `u16` | taille de l'en-tête (32) |
| 8 | `u16` | `stageW` (ex. 240) |
| 10 | `u16` | `stageH` (ex. 320) |
| 12 | `u16` | nombre d'os |
| 14 | `u16` | nombre de parts |
| 16 | `u16` | nombre d'animations |
| 18 | `u16` | réservé (0) |
| 20 | `u32` | taille du bloc de pixels, en octets |
| 24 | `u32` | nombre de pixels RGB565 |
| 28 | `u32` | CRC32 (IEEE, celui de zlib) du bloc de pixels |

Le CRC permet de détecter un asset tronqué ou édité à la main : le chargeur
refuse le fichier si l'empreinte ne correspond pas.

## Os — 12 octets par os

| Offset | Type | Champ |
| ---: | :--- | :--- |
| 0 | `i16` | index du parent (`-1` = racine) |
| 2 | `i16` | `restX` relatif **à la tête du parent** |
| 4 | `i16` | `restY` |
| 6 | `i16` | angle de repos (dixièmes de degré) |
| 8 | `u32` | réservé |

**Invariant** : un os ne peut référencer qu'un parent d'index **strictement
inférieur**. Le moteur résout donc la hiérarchie en une seule passe, et le packer
refuse un rig qui ne respecte pas cet ordre.

`rest` est relatif à la tête du parent (et non à sa queue) : chaque os est un
**pivot**, et un enfant suit le pivot de son parent.

## Parts — 26 octets par part

| Offset | Type | Champ |
| ---: | :--- | :--- |
| 0 | `i16` | os qui porte la part (`-1` = aucun) |
| 2 | `i16` | `pivotX` dans la case sprite |
| 4 | `i16` | `pivotY` |
| 6 | `u16` | `spriteW` |
| 8 | `u16` | `spriteH` |
| 10 | `u16` | ordre de dessin (croissant : 0 = derrière) |
| 12 | `u16` | drapeaux (réservé, 0) |
| 14 | `u16` | réservé |
| 16 | `u16` | réservé |
| 18 | `u32` | `pixelOffset` (octet du coin haut-gauche dans le bloc) |
| 22 | `u32` | `pixelBytes` (taille de la case) |

Les cases sont stockées **contiguës** (lignes qui se suivent, largeur =
`spriteW`) : le moteur n'a pas de calcul de stride à faire, il pointe
directement dans le bloc. Les parts sont écrites dans l'ordre de dessin, du fond
vers l'avant.

## Animations

Chaque animation commence par :

| Type | Champ |
| :--- | :--- |
| `u16` | longueur du nom (octets) |
| `char[]` | nom en UTF-8, sans zéro terminal |
| `u16` | drapeaux : bit 0 = **boucle** |
| `u16` | nombre de clés |
| `u32` | durée en millisecondes |

Puis, pour chaque clé :

| Type | Champ |
| :--- | :--- |
| `u16` | `tMs` (croissant) |
| `i16 × 5` | pose de l'os 0 : `dx, dy, rot, sx, sy` |
| … | … une pose par os, dans l'ordre du squelette |

Chaque clé porte **toutes** les poses (pas de compression) : le moteur cherche
l'intervalle `[k0, k1]` et interpole linéairement les cinq composantes —
`dx`/`dy` en pixels, `rot` en dixièmes de degré, `sx`/`sy` en 1/10000
(`10000` = ×1). Lecture d'une clé : `O(nb os)` par image, sans allocation.

Règles de lecture :

* animation **en boucle** : `t = temps_ecoule mod duree`, et `t = duree` doit
  redonner exactement la pose de `t = 0` (vérifié par `iska_clip_check.py`) ;
* animation **one-shot** : au-delà de la durée, la dernière pose est tenue ;
  l'hôte peut tester `Player::finished()` pour enchaîner.

## Poses et transformations

Une pose donnée par l'hôte est un **delta par rapport au repos** du rig :

```
local_x = restX + dx        local_angle = angle_repos + rot
local_y = restY + dy        local_scale = (sx, sy)
```

Résolution de la hiérarchie, pour chaque os (parents d'abord) :

```
position(os) = position(parent) + R(angle(parent)) · (echelle(parent) ⊙ (local_x, local_y))
angle(os)    = angle(parent) + local_angle
echelle(os)  = local_scale                      <- NON héritée
```

L'échelle **n'est pas héritée** : réduire le torse ne déforme pas la tête, il la
fait seulement descendre (utile pour un *squash and stretch*), et une échelle
n'affecte que la part dessinée par l'os qui la porte. C'est un choix assumé —
les deux implémentations font exactement pareil.

Dessin d'une part (`P` = pivot dans la case, `J` = articulation de son os) :

```
avant   : dst = J + R(angle) · (S · (p - P))
arrière : p   = P + S⁻¹ · R(-angle) · (dst - J)      <- ce que fait le blitter
```

Le blitter parcourt la boîte englobante des quatre coins tournés, applique la
formule arrière pour chaque centre de pixel, et échantillonne **le plus proche
voisin**. Un pixel magenta n'est jamais écrit, donc les bords restent nets (pas
de mélange) — c'est ce qu'on veut en pixel art sur un écran RGB565.

## Écriture des animations (JSON → binaire)

Les animations s'écrivent en JSON (`tools/animations/*.json`) puis sont
empaquetées. Deux règles rendent l'écriture manuelle supportable :

1. **Os absent d'une clé = valeur de la clé précédente** (« canal sparse »,
   comme les canaux Blender). Un os qui ne bouge pas ne s'écrit pas.
2. **Os cité = ses composantes non précisées repassent au repos.** Pour renvoyer
   un os au repos, on l'écrit donc explicitement : `"armL": {}`.

La règle est appliquée en un seul endroit (`iska_common.carry_keys`), utilisé à
la fois par le générateur d'animations et par le packer.

## Exemple d'asset

`assets/rabbit3.iska` (60 ko) :

| | |
| :--- | :--- |
| Panneau | 240 × 320 |
| Os | 11 (`root`, `torso`, `head`, `earL/R`, `eyeL/R`, `armL/R`, `footL/R`) |
| Parts | 10 (une par os sauf `root`) |
| Animations | `idle_loop` (2400 ms, boucle, 28 clés) — `peek` (2700 ms, one-shot, 20 clés) |
| Bloc pixels | 55 486 octets (10 cases RGB565) |
| Total | 61 319 octets |

## Compatibilité / évolution

* Le champ `version` de l'en-tête permet d'introduire un format v2 sans
  ambiguïté : `Iska::parseAsset` refuse toute version qu'il ne connaît pas, avec
  un message explicite, plutôt que de lire de travers.
* Les champs `reserved`, `flags` et le bit 1+ des drapeaux d'animation sont
  libres : c'est là qu'ira par exemple un miroir de sprite (`FLIP_X`) ou une
  interpolation non linéaire par clé.
* Les noms d'os et de parts **ne sont pas stockés** : le moteur travaille par
  index. L'outillage Python leur donne des noms internes (`os0`, `part0`) quand
  il relit un binaire, et s'appuie sur les JSON pour les noms réels.

