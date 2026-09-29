#pragma once

#include <cstdint>

struct SDL_Renderer;

/**
 * API d'affichage compatible Intellar-Engine (ILI9341).
 *
 * Profil par defaut : **paysage 320×240** (UI d'origine du moteur). Un hote peut
 * demander un autre panneau AVANT `initLCD()` — `Drivers::setPanelSize(240, 320)`
 * reproduit la dalle **portrait du setup reel** (stage 240×240 centre en (0, 40)).
 * Implementation PC : SDL2 — voir src/Drivers/LCD.cpp
 */
namespace Drivers {

#define TFT_BLACK    0x0000
#define TFT_NAVY     0x000F
#define TFT_MAROON   0x7800
#define TFT_DARKGREY 0x7BEF
#define TFT_BLUE     0x001F
#define TFT_GREEN    0x07E0
#define TFT_CYAN     0x07FF
#define TFT_RED      0xF800
#define TFT_MAGENTA  0xF81F
#define TFT_YELLOW   0xFFE0
#define TFT_WHITE    0xFFFF
#define TFT_ORANGE   0xFDA0
#define TFT_PINK     0xFC9F

enum class DisplayIndex { LEFT, RIGHT };

constexpr int kDefaultScreenWidth  = 320;
constexpr int kDefaultScreenHeight = 240;
constexpr int kSpriteSize          = 240;   // stage du moteur (SkeletalPlayer)

namespace detail {
/** Geometrie du panneau : etat inline -> partage entre TOUTES les unites de
 *  compilation sans exiger le lien vers LCD.cpp (les tests hote n'embarquent
 *  pas SDL). */
inline int&  panelWidth()  { static int w = kDefaultScreenWidth;  return w; }
inline int&  panelHeight() { static int h = kDefaultScreenHeight; return h; }
inline bool& panelLocked() { static bool l = false;               return l; }
}  // namespace detail

/** Dimensions du panneau actif, en pixels. */
inline int screenWidth() { return detail::panelWidth(); }
inline int screenHeight() { return detail::panelHeight(); }
/** Coin haut-gauche du stage 240×240 dans le panneau (centre). */
inline int spriteOffsetX() { return (screenWidth() - kSpriteSize) / 2; }
inline int spriteOffsetY() { return (screenHeight() - kSpriteSize) / 2; }

/** Choisit la geometrie du panneau — a appeler AVANT initLCD()
 *  (ex. `setPanelSize(240, 320)` pour la dalle portrait du setup reel).
 *  Sans effet une fois l'ecran initialise. */
inline void setPanelSize(int width, int height) {
    if (detail::panelLocked()) return;
    if (width > 0)  detail::panelWidth()  = width;
    if (height > 0) detail::panelHeight() = height;
}

void initLCD(uint8_t cs, uint8_t dc, uint8_t rst, uint8_t led);
void clearLCD();
void drawTouchMarker(int x, int y);
void displayTouchCoords(int x, int y);
void setAnimation(const char* filename, DisplayIndex display = DisplayIndex::LEFT);
void updateLCD();
void showCatFace(int leftIndex, int rightIndex);
void pushVideo565(DisplayIndex which, const uint16_t* rgb565);
/** Framebuffer plein écran 320×240 RGB565 (MJPEG, etc.). */
void pushScreen565(const uint16_t* rgb565);
void loadRobotEyeRes(const char* filename);
void showRobotEyes(float normX, float normY, const uint16_t* grid = nullptr);
bool isRobotEyeResourceReady();
bool haveCatStripAtlas();
/** Nombre de colonnes 240 px dans le strip chargé (0 si aucun atlas). */
int stripColumnCount(DisplayIndex display = DisplayIndex::LEFT);
void reportTimings();

bool tftTouchSubsystemReady();
void drawTftTouchFeedback();
bool getIli9341TouchScreenPos(int16_t* outX, int16_t* outY);

/** Traite clavier / souris SDL ; retourne false si l'utilisateur ferme la fenêtre. */
bool pumpEvents();

/** Enregistre la fenêtre telle qu'elle est a l'ecran (BMP) — outil de capture. */
bool saveScreenshot(const char* path);

/** Dessin par-dessus la fenêtre SDL après le framebuffer (simulateur, optionnel). */
using SimOverlayDrawFn = void (*)(::SDL_Renderer* renderer, int windowScale, void* userdata);
void setSimOverlayDraw(SimOverlayDrawFn fn, void* userdata = nullptr);

/** Répertoire des assets (défaut : ./data). */
void setDataDirectory(const char* path);
const char* getDataDirectory();

}  // namespace Drivers
