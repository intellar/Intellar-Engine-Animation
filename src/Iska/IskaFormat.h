#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

/**
 * Format **ISKA v1** — squelette + animations + pixels, en un seul fichier.
 *
 * Tout est en petit-boutiste et en **pixels ecran** (X vers la droite, Y vers le
 * bas, angles en degres **horaires**). Le fichier est produit par
 * `tools/iska_pack.py` ; il est autonome : ni Blender, ni PNG, ni SDL pour le
 * lire. Le meme format est implemente en Python dans `tools/iska_common.py`
 * (utile pour comparer les deux rendus image par image).
 *
 * En-tete (32 o) :
 *   "ISKA"               4 o
 *   u16 version          1
 *   u16 headerBytes      32
 *   u16 stageW, u16 stageH        (panneau, ex. 240x320)
 *   u16 boneCount, u16 partCount, u16 animCount
 *   u16 reserved (0)
 *   u32 pixelBytes               (taille du bloc de pixels)
 *   u32 pixelCount               (nombre de pixels RGB565)
 *   u32 pixelCrc32               (CRC32 du bloc de pixels)
 *
 * Os (boneCount x 12 o) : i16 parent (-1 = racine), i16 restX, i16 restY,
 *                         i16 restAngle (dixiemes de degre), u32 reserved
 *   `rest` est la position de l'os **relative a la tete de son parent** : le
 *   moteur part de la racine et descend l'arbre. Les parents precedent toujours
 *   leurs enfants (invariant verifie par le packer).
 *
 * Part (partCount x 26 o) : i16 bone (-1 = aucune), i16 pivotX, i16 pivotY,
 *                           u16 spriteW, u16 spriteH, u16 drawOrder, u16 flags,
 *                           u16 reserved, u16 reserved2,
 *                           u32 pixelOffset (octets), u32 pixelBytes
 *   La case sprite est **contigue** dans le bloc de pixels : `pixelOffset` est
 *   l'octet de son coin haut-gauche, les lignes se suivent.
 *
 * Animation (animCount enregistrements, a la suite) :
 *   u16 nameLen, nom UTF-8, u16 flags (bit0 = boucle), u16 keyCount,
 *   u32 durationMs,
 *   keyCount x { u16 tMs, boneCount x (i16 dx, i16 dy, i16 rot, i16 sx, i16 sy) }
 *   dx/dy en pixels, rot en dixiemes de degre, sx/sy en 1/10000 (10000 = x1).
 *   Chaque cle porte **toutes** les poses d'os (pas de compression) : le moteur
 *   se contente d'interpoler lineairement entre deux cles.
 *
 * Pixels : bloc RGB565, cases concatenees dans l'ordre des `partCount`.
 *   Un pixel **magenta** (0xF81F) n'est jamais ecrit : c'est la cle de
 *   transparence (voir docs/FORMAT.md).
 *
 * Transformations (identiques dans `tools/iska_common.py`) :
 *   monde(os)  = parent.pos + R(parent.angle) * (parent.echelle . rest(os))
 *   angle(os)  = parent.angle + angle_local(os)
 *   echelle(os)= echelle locale de l'os       <- NON heritee (squash and stretch)
 *   part       : p_ecran = pivot + S^-1 * R(-angle) * (point - articulation)
 */
namespace Iska {

constexpr char     kMagic[4]      = {'I', 'S', 'K', 'A'};
constexpr uint16_t kFormatVersion = 1;
constexpr size_t   kHeaderBytes   = 32;
constexpr size_t   kBoneBytes     = 12;
constexpr size_t   kPartBytes     = 26;
constexpr size_t   kKeyPoseBytes  = 10;   // dx, dy, rot, sx, sy

constexpr uint16_t kAnimFlagLoop = 0x0001;
constexpr uint16_t kColorKey     = 0xF81F;   // magenta : jamais dessine

constexpr float kAngleScale = 10.0f;      // angles stockes en dixiemes de degre
constexpr float kFixedScale = 10000.0f;   // echelles stockees en 1/10000

// Meme conversion degres -> radians que `math.radians` de Python (produit en
// radians constants) : indispensable pour que les deux rendus tombent sur les
// memes pixels.
constexpr double kPi       = 3.14159265358979323846;
constexpr double kDegToRad = kPi / 180.0;

inline uint16_t readU16(const uint8_t* p) {
    return static_cast<uint16_t>(p[0] | (static_cast<uint16_t>(p[1]) << 8));
}

inline int16_t readI16(const uint8_t* p) {
    return static_cast<int16_t>(readU16(p));
}

inline uint32_t readU32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}

/** Un os : parent, position de repos (relative au parent) et angle de repos. */
struct Bone {
    int16_t parent = -1;      // index, -1 = racine
    double  restX  = 0.0;
    double  restY  = 0.0;
    double  angle  = 0.0;    // degres, horaire
};

/** Une part : l'os qui la porte, son pivot dans la case, sa case dans l'atlas. */
struct Part {
    int16_t  bone        = -1;
    int16_t  pivotX      = 0;
    int16_t  pivotY      = 0;
    uint16_t width       = 0;
    uint16_t height      = 0;
    uint16_t drawOrder   = 0;
    uint16_t flags       = 0;
    uint32_t pixelOffset = 0;   // octets dans Asset::pixelBytes
    uint32_t pixelCount  = 0;   // nombre de pixels RGB565 de la case
};

/** Une cle : instant (ms) et poses de tous les os (5 valeurs i16 par os). */
struct Key {
    uint16_t             tMs = 0;
    std::vector<int16_t> pose;   // [dx, dy, rot, sx, sy] x boneCount
};

struct Animation {
    std::string        name;
    bool               loop       = false;
    uint32_t           durationMs = 0;
    std::vector<Key>   keys;
};

/** Un asset .iska charge en memoire (tout est possede par valeur : copiable). */
struct Asset {
    uint16_t                 stageW = 0;
    uint16_t                 stageH = 0;
    std::vector<Bone>        bones;
    std::vector<Part>        parts;
    std::vector<Animation>   animations;
    std::vector<uint16_t>    pixels;      // atlas RGB565 (cases concatenees)
    size_t                   fileBytes = 0;

    /** Premiere animation dont le nom correspond, ou nullptr. */
    const Animation* find(const char* name) const;
    const Animation* find(const std::string& name) const { return find(name.c_str()); }
};

}  // namespace Iska
