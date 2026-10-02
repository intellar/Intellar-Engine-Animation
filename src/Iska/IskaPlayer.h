#pragma once

#include <cstdint>
#include <vector>

#include "IskaFormat.h"

namespace Iska {

/** Per-bone deltas at a given time (in format units).

 *  Pose maths uses `double` (not `float`): that is what guarantees that
 *  `tools/iska_common.py` (Python) and the runtime produce the same image down
 *  to the pixel -- with `float`, a single last-digit rounding error is enough
 *  to make a nearest-neighbour sample land on a different texel.
 */
struct BonePose {
    double dx = 0.0, dy = 0.0, rot = 0.0, sx = 1.0, sy = 1.0;
};

/** Bone resolved into screen coordinates. */
struct BoneWorld {
    double x = 0.0, y = 0.0, angle = 0.0, sx = 1.0, sy = 1.0;
};

/**
 * ISKA animation player: advances the clock, samples the keys, resolves the
 * hierarchy and draws the parts into an RGB565 framebuffer.
 *
 * The `Player` does not own the `Asset`: it keeps a pointer, so the asset must
 * outlive the player (which is the case in the demo).
 */
class Player {
public:
    /** Binds an asset and selects the first animation (without playing it). */
    bool bind(const Asset* asset);

    /** Plays an animation by name. `restart` resets the time even when that
     *  animation is already the one being played. */
    bool play(const char* name, bool restart = false);
    bool playIndex(size_t index, bool restart = false);

    /** Advances the clock. Time is clamped (or wrapped) by the animation. */
    void update(uint32_t deltaMs);

    /** Sets the clock to an exact time (handy for frame capture). */
    void setTime(uint32_t tMs);

    /** Clears then draws the current pose (stageW*stageH framebuffer). */
    void render(uint16_t* buffer, uint16_t background = 0x0000) const;

    /** Draws the current pose without clearing (to compose over a backdrop). */
    void draw(uint16_t* buffer) const;

    const Animation* animation() const { return animation_; }
    const char*      animationName() const { return animation_ ? animation_->name.c_str() : ""; }
    uint32_t         timeMs() const { return timeMs_; }
    /** True once a one-shot animation has reached its end. */
    bool             finished() const;
    bool             looping() const { return animation_ && animation_->loop; }

    int stageWidth() const { return asset_ ? asset_->stageW : 0; }
    int stageHeight() const { return asset_ ? asset_->stageH : 0; }

    /** Sampled poses from the last update (read-only / debugging). */
    const std::vector<BonePose>& pose() const { return pose_; }
    /** Screen positions of the bones from the last update (read-only / debugging). */
    const std::vector<BoneWorld>& world() const { return world_; }

    /** Samples the keys of an animation without touching the current playback. */
    static std::vector<BonePose> samplePose(const Animation& anim, uint32_t tMs, size_t boneCount);
    /** Resolves the hierarchy: screen positions, angles and scales. */
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
