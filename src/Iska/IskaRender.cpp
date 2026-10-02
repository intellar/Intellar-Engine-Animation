#include "IskaRender.h"

#include <cmath>

namespace Iska {

void fill(uint16_t* dst, int width, int height, uint16_t color) {
    if (!dst) return;
    const int count = width * height;
    for (int i = 0; i < count; i++) dst[i] = color;
}

void blitPart(uint16_t* dst, int dstW, int dstH,
              const uint16_t* sprite, int spriteW, int spriteH,
              double pivotX, double pivotY,
              double jointX, double jointY,
              double angleDeg, double scaleX, double scaleY) {
    if (!dst || !sprite || spriteW <= 0 || spriteH <= 0 || dstW <= 0 || dstH <= 0) return;
    // a null scale makes no sense: clamp it (as the Python side does)
    const double sx = (std::fabs(scaleX) > 1e-6) ? scaleX : 1e-6;
    const double sy = (std::fabs(scaleY) > 1e-6) ? scaleY : 1e-6;

    // same conversion as Python's math.radians() (angDeg * (pi / 180))
    const double a     = angleDeg * kDegToRad;
    const double cosA  = std::cos(a);
    const double sinA  = std::sin(a);
    const double px    = pivotX;
    const double py    = pivotY;
    const double jx    = jointX;
    const double jy    = jointY;

    // bounding box of the four corners of the box, after rotation + scaling
    const double cxs[4] = {0.0, static_cast<double>(spriteW), static_cast<double>(spriteW), 0.0};
    const double cys[4] = {0.0, 0.0, static_cast<double>(spriteH), static_cast<double>(spriteH)};
    double minX = 0.0, minY = 0.0, maxX = 0.0, maxY = 0.0;
    for (int i = 0; i < 4; i++) {
        const double ux = (cxs[i] - px) * sx;
        const double uy = (cys[i] - py) * sy;
        const double wx = jx + ux * cosA - uy * sinA;
        const double wy = jy + ux * sinA + uy * cosA;
        if (i == 0) {
            minX = maxX = wx;
            minY = maxY = wy;
        } else {
            if (wx < minX) minX = wx;
            if (wx > maxX) maxX = wx;
            if (wy < minY) minY = wy;
            if (wy > maxY) maxY = wy;
        }
    }
    int x0 = static_cast<int>(std::floor(minX));
    int x1 = static_cast<int>(std::ceil(maxX));
    int y0 = static_cast<int>(std::floor(minY));
    int y1 = static_cast<int>(std::ceil(maxY));
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > dstW - 1) x1 = dstW - 1;
    if (y1 > dstH - 1) y1 = dstH - 1;

    const double invSx = 1.0 / sx;
    const double invSy = 1.0 / sy;
    for (int y = y0; y <= y1; y++) {
        const double dy  = (static_cast<double>(y) + 0.5) - jy;
        uint16_t*     row = dst + static_cast<size_t>(y) * dstW;
        for (int x = x0; x <= x1; x++) {
            const double dx = (static_cast<double>(x) + 0.5) - jx;
            // R(-a), then the inverse of the scale, then back into the sprite box
            const double rx = dx * cosA + dy * sinA;
            const double ry = -dx * sinA + dy * cosA;
            const double u  = px + rx * invSx;
            const double v  = py + ry * invSy;
            if (u < 0.0 || v < 0.0) continue;
            const int iu = static_cast<int>(u);
            const int iv = static_cast<int>(v);
            if (iu >= spriteW || iv >= spriteH) continue;
            const uint16_t value = sprite[static_cast<size_t>(iv) * spriteW + iu];
            if (value == kColorKey) continue;
            row[x] = value;
        }
    }
}

}  // namespace Iska
