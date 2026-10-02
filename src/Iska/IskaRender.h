#pragma once

#include <cstdint>

#include "IskaFormat.h"

namespace Iska {

/**
 * Draws an RGB565 sprite box **rotated around its pivot**, with
 * nearest-neighbour sampling. Magenta pixels (the transparency key) are never
 * written.
 *
 *   p_screen = pivot + S^-1 * R(-angle) * (point - joint)
 *
 * This is the same formula as `blit_part` in tools/iska_common.py: both
 * implementations are deliberately identical so the engine frames and the
 * Python tooling frames can be compared pixel by pixel.
 *
 * @param dst        RGB565 framebuffer (dstW x dstH)
 * @param sprite     pixels of the box (spriteW x spriteH, contiguous)
 * @param pivot      pivot inside the box, in pixels (may fall outside the box)
 * @param joint      screen position of the joint (the bone)
 * @param angleDeg   rotation in degrees, clockwise on screen
 * @param scaleX/Y   scale of the part (1 = size of the box)
 */
void blitPart(uint16_t* dst, int dstW, int dstH,
              const uint16_t* sprite, int spriteW, int spriteH,
              double pivotX, double pivotY,
              double jointX, double jointY,
              double angleDeg, double scaleX, double scaleY);

/** Fills an RGB565 framebuffer with a solid colour. */
void fill(uint16_t* dst, int width, int height, uint16_t color);

}  // namespace Iska
