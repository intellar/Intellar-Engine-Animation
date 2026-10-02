#include "IskaPlayer.h"

#include <cmath>

#include "IskaRender.h"

namespace Iska {

bool Player::bind(const Asset* asset) {
    asset_ = asset;
    if (!asset_ || asset_->bones.empty()) {
        animation_ = nullptr;
        return false;
    }
    pose_.assign(asset_->bones.size(), BonePose{});
    world_.assign(asset_->bones.size(), BoneWorld{});
    timeMs_ = 0;
    if (!asset_->animations.empty()) {
        animation_ = &asset_->animations.front();
        resample();
    }
    return true;
}

bool Player::play(const char* name, bool restart) {
    if (!asset_) return false;
    const Animation* anim = asset_->find(name);
    if (!anim) return false;
    if (anim == animation_ && !restart) return true;
    animation_ = anim;
    timeMs_    = 0;
    resample();
    return true;
}

bool Player::playIndex(size_t index, bool restart) {
    if (!asset_ || index >= asset_->animations.size()) return false;
    const Animation* anim = &asset_->animations[index];
    if (anim == animation_ && !restart) return true;
    animation_ = anim;
    timeMs_    = 0;
    resample();
    return true;
}

void Player::update(uint32_t deltaMs) {
    if (!animation_) return;
    timeMs_ += deltaMs;
    if (animation_->loop) {
        if (animation_->durationMs > 0) timeMs_ %= animation_->durationMs;
    } else if (timeMs_ > animation_->durationMs) {
        timeMs_ = animation_->durationMs;
    }
    resample();
}

void Player::setTime(uint32_t tMs) {
    timeMs_ = tMs;
    resample();
}

bool Player::finished() const {
    return animation_ && !animation_->loop && timeMs_ >= animation_->durationMs;
}

void Player::resample() {
    if (!asset_ || !animation_) return;
    pose_  = samplePose(*animation_, timeMs_, asset_->bones.size());
    world_ = resolveBones(*asset_, pose_);
}


std::vector<BonePose> Player::samplePose(const Animation& anim, uint32_t tMs,
                                        size_t boneCount) {
    std::vector<BonePose> pose(boneCount);
    if (anim.keys.empty()) return pose;
    if (tMs < anim.keys.front().tMs) tMs = anim.keys.front().tMs;
    const bool pastEnd = tMs >= anim.keys.back().tMs;
    if (pastEnd) tMs = anim.keys.back().tMs;

    const Key* k0 = &anim.keys.front();
    const Key* k1 = &anim.keys.front();
    double     u  = 0.0;
    if (!pastEnd) {
        for (size_t i = 1; i < anim.keys.size(); i++) {
            if (tMs <= anim.keys[i].tMs) {
                k0 = &anim.keys[i - 1];
                k1 = &anim.keys[i];
                const uint32_t span = k1->tMs - k0->tMs;
                u = (span == 0) ? 0.0
                                : static_cast<double>(tMs - k0->tMs) / static_cast<double>(span);
                break;
            }
        }
    }
    for (size_t b = 0; b < boneCount; b++) {
        const size_t base = b * 5;
        const double start[5] = {static_cast<double>(k0->pose[base + 0]),
                                 static_cast<double>(k0->pose[base + 1]),
                                 static_cast<double>(k0->pose[base + 2]) / kAngleScale,
                                 static_cast<double>(k0->pose[base + 3]) / kFixedScale,
                                 static_cast<double>(k0->pose[base + 4]) / kFixedScale};
        const double end[5]   = {static_cast<double>(k1->pose[base + 0]),
                                 static_cast<double>(k1->pose[base + 1]),
                                 static_cast<double>(k1->pose[base + 2]) / kAngleScale,
                                 static_cast<double>(k1->pose[base + 3]) / kFixedScale,
                                 static_cast<double>(k1->pose[base + 4]) / kFixedScale};
        BonePose& p = pose[b];
        p.dx  = start[0] + (end[0] - start[0]) * u;
        p.dy  = start[1] + (end[1] - start[1]) * u;
        p.rot = start[2] + (end[2] - start[2]) * u;
        p.sx  = start[3] + (end[3] - start[3]) * u;
        p.sy  = start[4] + (end[4] - start[4]) * u;
    }
    return pose;
}


std::vector<BoneWorld> Player::resolveBones(const Asset& asset,
                                           const std::vector<BonePose>& pose) {
    std::vector<BoneWorld> world(asset.bones.size());
    for (size_t i = 0; i < asset.bones.size(); i++) {
        const Bone&    bone  = asset.bones[i];
        const BonePose local = (i < pose.size()) ? pose[i] : BonePose{};
        const double   lx    = bone.restX + local.dx;
        const double   ly    = bone.restY + local.dy;
        const double   angle = bone.angle + local.rot;

        BoneWorld& out = world[i];
        if (bone.parent < 0) {
            out.x     = lx;
            out.y     = ly;
            out.angle = angle;
            out.sx    = local.sx;
            out.sy    = local.sy;
            continue;
        }
        const BoneWorld& parent = world[bone.parent];
        const double     ux     = lx * parent.sx;
        const double     uy     = ly * parent.sy;
        // Python's `math.radians(x)` == x * (pi / 180): same order of operations
        const double     rad    = parent.angle * kDegToRad;
        const double     cosA   = std::cos(rad);
        const double     sinA   = std::sin(rad);
        out.x     = parent.x + (ux * cosA - uy * sinA);
        out.y     = parent.y + (ux * sinA + uy * cosA);
        out.angle = parent.angle + angle;
        // the scale is NOT inherited: it only affects the part drawn by this bone
        out.sx    = local.sx;
        out.sy    = local.sy;
    }
    return world;
}

void Player::draw(uint16_t* buffer) const {
    if (!asset_ || !buffer) return;
    for (const Part& part : asset_->parts) {
        if (part.bone < 0 || static_cast<size_t>(part.bone) >= world_.size()) continue;
        const BoneWorld& bone = world_[part.bone];
        const uint16_t*  pix  = asset_->pixels.data() + part.pixelOffset / 2;
        blitPart(buffer, asset_->stageW, asset_->stageH, pix, part.width, part.height,
                 static_cast<double>(part.pivotX), static_cast<double>(part.pivotY),
                 bone.x, bone.y, bone.angle, bone.sx, bone.sy);
    }
}

void Player::render(uint16_t* buffer, uint16_t background) const {
    if (!asset_ || !buffer) return;
    fill(buffer, asset_->stageW, asset_->stageH, background);
    draw(buffer);
}

}  // namespace Iska
