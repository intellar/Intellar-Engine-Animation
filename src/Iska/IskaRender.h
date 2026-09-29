#pragma once

#include <cstdint>

#include "IskaFormat.h"

namespace Iska {

/**
 * Dessine une case sprite RGB565 **tournee autour de son pivot**, en
 * reechantillonnage plus proche voisin. Les pixels magenta (cle de transparence)
 * ne sont jamais ecrits.
 *
 *   p_ecran = pivot + S^-1 * R(-angle) * (point - articulation)
 *
 * C'est la meme formule que `blit_part` de tools/iska_common.py : les deux
 * implementations sont volontairement identiques pour pouvoir comparer les
 * images du moteur et celles de l'outillage Python au pixel pres.
 *
 * @param dst        framebuffer RGB565 (dstW x dstH)
 * @param sprite     pixels de la case (spriteW x spriteH, contigus)
 * @param pivot      pivot dans la case, en pixels (peut sortir de la case)
 * @param joint      position ecran de l'articulation (l'os)
 * @param angleDeg   rotation en degres, horaire a l'ecran
 * @param scaleX/Y   echelle de la part (1 = taille de la case)
 */
void blitPart(uint16_t* dst, int dstW, int dstH,
              const uint16_t* sprite, int spriteW, int spriteH,
              double pivotX, double pivotY,
              double jointX, double jointY,
              double angleDeg, double scaleX, double scaleY);

/** Remplit un framebuffer RGB565 d'une couleur unie. */
void fill(uint16_t* dst, int width, int height, uint16_t color);

}  // namespace Iska
