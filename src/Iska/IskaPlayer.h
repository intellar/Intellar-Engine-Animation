#pragma once

#include <cstdint>
#include <vector>

#include "IskaFormat.h"

namespace Iska {

/** Deltas d'un os a un instant donne (en unites du format).

 *  Les calculs de pose sont en `double` (et non en `float`) : c'est ce qui
 *  garantit que `tools/iska_common.py` (Python) et le moteur produisent la meme
 *  image au pixel pres -- en `float`, un arrondi de derniere decimale suffit a
 *  faire tomber un echantillon voisin plus proche sur un autre texel.
 */
struct BonePose {
    double dx = 0.0, dy = 0.0, rot = 0.0, sx = 1.0, sy = 1.0;
};

/** Os resolu en coordonnees ecran. */
struct BoneWorld {
    double x = 0.0, y = 0.0, angle = 0.0, sx = 1.0, sy = 1.0;
};

/**
 * Lecteur d'animations ISKA : avance le temps, echantillonne les cles, resout
 * la hierarchie et dessine les parts dans un framebuffer RGB565.
 *
 * Le `Player` ne possede pas l'`Asset` : il garde un pointeur, l'asset doit donc
 * vivre plus longtemps que le lecteur (c'est le cas dans la demo).
 */
class Player {
public:
    /** Associe un asset et se place sur la premiere animation (sans la jouer). */
    bool bind(const Asset* asset);

    /** Joue une animation par son nom. `restart` remet le temps a zero meme si
     *  l'animation est deja celle qui joue. */
    bool play(const char* name, bool restart = false);
    bool playIndex(size_t index, bool restart = false);

    /** Avance l'horloge. Le temps est borne (ou boucle) selon l'animation. */
    void update(uint32_t deltaMs);

    /** Place l'horloge a un instant precis (utile pour la capture d'images). */
    void setTime(uint32_t tMs);

    /** Efface puis dessine la pose courante (framebuffer de stageW*stageH). */
    void render(uint16_t* buffer, uint16_t background = 0x0000) const;

    /** Dessine la pose courante sans effacer (pour composer avec un decor). */
    void draw(uint16_t* buffer) const;

    const Animation* animation() const { return animation_; }
    const char*      animationName() const { return animation_ ? animation_->name.c_str() : ""; }
    uint32_t         timeMs() const { return timeMs_; }
    /** Vrai quand une animation one-shot est arrivee au bout. */
    bool             finished() const;
    bool             looping() const { return animation_ && animation_->loop; }

    int stageWidth() const { return asset_ ? asset_->stageW : 0; }
    int stageHeight() const { return asset_ ? asset_->stageH : 0; }

    /** Poses echantillonnees de la derniere mise a jour (lecture/debug). */
    const std::vector<BonePose>& pose() const { return pose_; }
    /** Positions ecran des os de la derniere mise a jour (lecture/debug). */
    const std::vector<BoneWorld>& world() const { return world_; }

    /** Echantillonne les cles d'une animation sans toucher a la lecture en cours. */
    static std::vector<BonePose> samplePose(const Animation& anim, uint32_t tMs, size_t boneCount);
    /** Resout la hierarchie : positions, angles et echelles ecran. */
    static std::vector<BoneWorld> resolveBones(const Asset& asset,
                                               const std::vector<BonePose>& pose);

private:
    void resample();

    const Asset*      asset_     = nullptr;
    const Animation*  animation_ = nullptr;
    uint32_t          timeMs_    = 0;
    std::vector<BonePose>  pose_;
    std::vector<BoneWorld> world_;
};

}  // namespace Iska
