#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

/**
 * **ISKA v1** format -- skeleton + animations + pixels in a single file.
 *
 * Everything is little-endian and expressed in **screen pixels** (X to the
 * right, Y downwards, angles in **clockwise** degrees). The file is produced by
 * `tools/iska_pack.py` and is self-contained: no Blender, no PNG and no SDL is
 * needed to read it. The same format is implemented in Python in
 * `tools/iska_common.py` (handy to compare the two renderers image by image).
 *
 * Header (32 B):
 *   "ISKA"               4 B
 *   u16 version          1
 *   u16 headerBytes      32
 *   u16 stageW, u16 stageH        (panel, e.g. 240x320)
 *   u16 boneCount, u16 partCount, u16 animCount
 *   u16 reserved (0)
 *   u32 pixelBytes               (size of the pixel block)
 *   u32 pixelCount               (number of RGB565 pixels)
 *   u32 pixelCrc32               (CRC32 of the pixel block)
 *
 * Bones (boneCount x 12 B): i16 parent (-1 = root), i16 restX, i16 restY,
 *                           i16 restAngle (tenths of a degree), u32 reserved
 *   `rest` is the bone position **relative to its parent's head**: the runtime
 *   starts at the root and walks down the tree. Parents always precede their
 *   children (invariant enforced by the packer).
 *
 * Parts (partCount x 26 B): i16 bone (-1 = none), i16 pivotX, i16 pivotY,
 *                           u16 spriteW, u16 spriteH, u16 drawOrder, u16 flags,
 *                           u16 reserved, u16 reserved2,
 *                           u32 pixelOffset (bytes), u32 pixelBytes
 *   The sprite box is **contiguous** in the pixel block: `pixelOffset` is the
 *   byte of its top-left corner and the rows follow each other.
 *
 * Animations (animCount records, right after the parts):
 *   u16 nameLen, UTF-8 name, u16 flags (bit0 = loop), u16 keyCount,
 *   u32 durationMs,
 *   keyCount x { u16 tMs, boneCount x (i16 dx, i16 dy, i16 rot, i16 sx, i16 sy) }
 *   dx/dy in pixels, rot in tenths of a degree, sx/sy in 1/10000 (10000 = x1).
 *   Every key carries **all** bone poses (no compression): the runtime simply
 *   interpolates linearly between two keys.
 *
 * Pixels: RGB565 block, boxes concatenated in `partCount` order.
 *   A **magenta** pixel (0xF81F) is never written: it is the transparency key
 *   (see docs/FORMAT.md).
 *
 * Transformations (identical in `tools/iska_common.py`):
 *   world(bone) = parent.pos + R(parent.angle) * (parent.scale . rest(bone))
 *   angle(bone) = parent.angle + local_angle(bone)
 *   scale(bone) = local scale of the bone   <- NOT inherited (squash & stretch)
 *   part        : p_screen = pivot + S^-1 * R(-angle) * (point - joint)
 */
namespace Iska {

constexpr char     kMagic[4]      = {'I', 'S', 'K', 'A'};
constexpr uint16_t kFormatVersion = 1;
constexpr size_t   kHeaderBytes   = 32;
constexpr size_t   kBoneBytes     = 12;
constexpr size_t   kPartBytes     = 26;
constexpr size_t   kKeyPoseBytes  = 10;   // dx, dy, rot, sx, sy

constexpr uint16_t kAnimFlagLoop = 0x0001;
constexpr uint16_t kColorKey     = 0xF81F;   // magenta: never drawn

constexpr float kAngleScale = 10.0f;      // angles stored in tenths of a degree
constexpr float kFixedScale = 10000.0f;   // scales stored in 1/10000

// Same degrees -> radians conversion as Python's `math.radians` (computed as a
// constant number of radians): required for both renderers to land on the same
// pixels.
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

/** A bone: parent, rest position (relative to the parent) and rest angle. */
struct Bone {
    int16_t parent = -1;      // index, -1 = root
    double  restX  = 0.0;
    double  restY  = 0.0;
    double  angle  = 0.0;     // degrees, clockwise
};

/** A part: the bone carrying it, its pivot inside the box, its box in the atlas. */
struct Part {
    int16_t  bone        = -1;
    int16_t  pivotX      = 0;
    int16_t  pivotY      = 0;
    uint16_t width       = 0;
    uint16_t height      = 0;
    uint16_t drawOrder   = 0;
    uint16_t flags       = 0;
    uint32_t pixelOffset = 0;   // bytes inside Asset::pixelBytes
    uint32_t pixelCount  = 0;   // number of RGB565 pixels in the box
};

/** A key: time (ms) and the poses of every bone (5 i16 values per bone). */
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

/** An .iska asset loaded in memory (everything is owned by value: copyable). */
struct Asset {
    uint16_t                 stageW = 0;
    uint16_t                 stageH = 0;
    std::vector<Bone>        bones;
    std::vector<Part>        parts;
    std::vector<Animation>   animations;
    std::vector<uint16_t>    pixels;     // RGB565 atlas (boxes concatenated)
    size_t                   fileBytes = 0;

    /** First animation whose name matches, or nullptr. */
    const Animation* find(const char* name) const;
    const Animation* find(const std::string& name) const { return find(name.c_str()); }
};

}  // namespace Iska
