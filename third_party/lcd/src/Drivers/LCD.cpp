#include "Drivers/LCD.h"

#include <SDL.h>

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr int kScale = 3;

SDL_Window*   g_window   = nullptr;
SDL_Renderer* g_renderer = nullptr;
SDL_Texture*  g_texture  = nullptr;

bool g_initialized = false;
bool g_quit          = false;

std::string g_dataDir = "data";  // partagé avec MjpegPlayer.cpp

int  g_mouseX = -1;
int  g_mouseY = -1;
bool g_mouseDown = false;
bool g_mousePressedLatch = false;
int  g_mouseLatchX = -1;
int  g_mouseLatchY = -1;

Drivers::SimOverlayDrawFn g_overlayDraw     = nullptr;
void*                     g_overlayUserdata = nullptr;

std::vector<uint16_t> g_screen;  // framebuffer du panneau actif (RGB565)

struct Atlas {
    std::vector<uint16_t> pixels;
    int                   sheetWidthPx = 1200;
    bool                  loaded       = false;
};

Atlas g_atlasLeft;
Atlas g_atlasRight;

uint16_t* g_sprite240 = nullptr;  // 240×240 travail

std::string resolvePath(const char* filename) {
    if (!filename || !filename[0]) return {};
    fs::path p(filename);
    if (p.is_absolute() && fs::exists(p)) return p.string();
    fs::path rel = fs::path(g_dataDir) / p.filename();
    if (fs::exists(rel)) return rel.string();
    if (fs::exists(p)) return p.string();
    return rel.string();
}

void freeAtlas(Atlas& a) {
    a.pixels.clear();
    a.loaded = false;
    a.sheetWidthPx = 1200;
}

bool loadAtlasFile(Atlas& atlas, const char* filename) {
    freeAtlas(atlas);
    const std::string path = resolvePath(filename);
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) {
        std::fprintf(stderr, "setAnimation: fichier introuvable %s\n", path.c_str());
        return false;
    }
    const auto fSize = static_cast<size_t>(file.tellg());
    if (fSize < 480) {
        std::fprintf(stderr, "setAnimation: fichier trop petit %s (%zu o)\n", path.c_str(), fSize);
        return false;
    }
    file.seekg(0);
    atlas.pixels.resize(fSize / 2);
    file.read(reinterpret_cast<char*>(atlas.pixels.data()), static_cast<std::streamsize>(fSize));
    if (static_cast<size_t>(file.gcount()) != fSize) {
        std::fprintf(stderr, "setAnimation: lecture incomplete %s\n", path.c_str());
        freeAtlas(atlas);
        return false;
    }
    if (fSize % 480 != 0) {
        std::fprintf(stderr,
                     "WARN: setAnimation %s taille %zu pas multiple de 480 (240×2)\n",
                     path.c_str(),
                     fSize);
    }
    const long delta = static_cast<long>(fSize) - 576000L;
    atlas.sheetWidthPx =
        (delta < 0 ? -delta : delta) < 4096 ? 1200 : static_cast<int>(fSize / 480);
    if (atlas.sheetWidthPx < 240) atlas.sheetWidthPx = 240;
    atlas.loaded = true;
    std::fprintf(stderr,
                 "INFO: setAnimation %s bytes=%zu sheetWidthPx=%d\n",
                 path.c_str(),
                 fSize,
                 atlas.sheetWidthPx);
    return true;
}

bool drawFaceToBuffer(uint16_t* dest, const Atlas& atlas, int index) {
    if (!atlas.loaded || atlas.pixels.empty() || !dest) return false;
    const int faceW = 240;
    int       cols  = atlas.sheetWidthPx / faceW;
    if (cols < 1) cols = 1;
    const int horizontalOffset = ((index % cols) + cols) % cols * faceW;
    const int sheetW             = atlas.sheetWidthPx;

    for (int y = 0; y < 240; y++) {
        std::memcpy(dest + y * 240,
                    atlas.pixels.data() + y * sheetW + horizontalOffset,
                    480);
    }
    return true;
}

uint32_t rgb565ToArgb(uint16_t c) {
    const uint8_t r = ((c >> 11) & 0x1F) * 255 / 31;
    const uint8_t g = ((c >> 5) & 0x3F) * 255 / 63;
    const uint8_t b = (c & 0x1F) * 255 / 31;
    return 0xFF000000u | (r << 16) | (g << 8) | b;
}

void presentScreen() {
    if (!g_texture || !g_renderer || g_screen.empty()) return;

    static std::vector<uint32_t> argb;
    argb.resize(g_screen.size());
    for (size_t i = 0; i < g_screen.size(); i++) argb[i] = rgb565ToArgb(g_screen[i]);

    SDL_UpdateTexture(g_texture,
                      nullptr,
                      argb.data(),
                      Drivers::screenWidth() * static_cast<int>(sizeof(uint32_t)));
    SDL_RenderClear(g_renderer);
    SDL_RenderCopy(g_renderer, g_texture, nullptr, nullptr);
    if (g_overlayDraw) {
        g_overlayDraw(g_renderer, kScale, g_overlayUserdata);
    }
    SDL_RenderPresent(g_renderer);
}

void blitSpriteCentered(const uint16_t* sprite240) {
    if (!sprite240) return;
    const int ox = Drivers::spriteOffsetX();
    const int oy = Drivers::spriteOffsetY();
    for (int y = 0; y < Drivers::kSpriteSize; y++) {
        std::memcpy(g_screen.data() + ((y + oy) * Drivers::screenWidth() + ox),
                    sprite240 + y * Drivers::kSpriteSize,
                    static_cast<size_t>(Drivers::kSpriteSize) * sizeof(uint16_t));
    }
}

}  // namespace

namespace Drivers {

void setDataDirectory(const char* path) {
    if (path && path[0]) g_dataDir = path;
}

const char* getDataDirectory() {
    return g_dataDir.c_str();
}

void setSimOverlayDraw(SimOverlayDrawFn fn, void* userdata) {
    g_overlayDraw     = fn;
    g_overlayUserdata = userdata;
}

bool pumpEvents() {
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
        switch (e.type) {
            case SDL_QUIT:
                g_quit = true;
                return false;
            case SDL_KEYDOWN:
                if (e.key.keysym.sym == SDLK_ESCAPE) {
                    g_quit = true;
                    return false;
                }
                break;
            case SDL_MOUSEMOTION:
                g_mouseX = e.motion.x / kScale;
                g_mouseY = e.motion.y / kScale;
                break;
            case SDL_MOUSEBUTTONDOWN:
                g_mouseDown = true;
                g_mouseX    = e.button.x / kScale;
                g_mouseY    = e.button.y / kScale;
                g_mousePressedLatch = true;
                g_mouseLatchX = g_mouseX;
                g_mouseLatchY = g_mouseY;
                break;
            case SDL_MOUSEBUTTONUP:
                g_mouseDown = false;
                break;
            default:
                break;
        }
    }
    return !g_quit;
}

void initLCD(uint8_t cs, uint8_t dc, uint8_t rst, uint8_t led) {
    (void)cs;
    (void)dc;
    (void)rst;
    (void)led;

    if (g_initialized) return;
    detail::panelLocked() = true;   // geometrie figee des l'init de l'ecran

    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        std::fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return;
    }

    g_screen.assign(static_cast<size_t>(screenWidth() * screenHeight()), TFT_BLACK);
    g_sprite240 = new uint16_t[static_cast<size_t>(kSpriteSize * kSpriteSize)];

    g_window = SDL_CreateWindow("Intellar Engine Simulator",
                                SDL_WINDOWPOS_CENTERED,
                                SDL_WINDOWPOS_CENTERED,
                                screenWidth() * kScale,
                                screenHeight() * kScale,
                                SDL_WINDOW_SHOWN);
    g_renderer =
        SDL_CreateRenderer(g_window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    g_texture = SDL_CreateTexture(g_renderer,
                                  SDL_PIXELFORMAT_ARGB8888,
                                  SDL_TEXTUREACCESS_STREAMING,
                                  screenWidth(),
                                  screenHeight());

    if (!g_window || !g_renderer || !g_texture) {
        std::fprintf(stderr, "SDL window/renderer: %s\n", SDL_GetError());
        return;
    }

    g_initialized = true;
    std::fprintf(stderr,
                 "[Simulator] ILI9341 %d×%d (fenêtre ×%d) — stage %d×%d en (%d,%d) — data: %s\n",
                 screenWidth(),
                 screenHeight(),
                 kScale,
                 kSpriteSize,
                 kSpriteSize,
                 spriteOffsetX(),
                 spriteOffsetY(),
                 g_dataDir.c_str());
}

void clearLCD() {
    if (!g_initialized) return;
    std::fill(g_screen.begin(), g_screen.end(), static_cast<uint16_t>(TFT_BLACK));
    presentScreen();
}

void drawTouchMarker(int x, int y) {
    if (!g_initialized || x < 0 || y < 0) return;

    // (x, y) arrivent en coordonnees ILI9341 (y = 0 en bas de l'ecran, x
    // miroir) ; le framebuffer du simulateur est en coordonnees ecran. Sans
    // cette inversion le marqueur s'affichait en miroir par rapport au clic.
    const int cx = screenWidth()  - 1 - x;
    const int cy = screenHeight() - 1 - y;

    for (int dy = -3; dy <= 3; dy++) {
        for (int dx = -3; dx <= 3; dx++) {
            const int px = cx + dx;
            const int py = cy + dy;
            if (px >= 0 && px < screenWidth() && py >= 0 && py < screenHeight())
                g_screen[static_cast<size_t>(py * screenWidth() + px)] =
                    static_cast<uint16_t>(TFT_YELLOW);
        }
    }
}

void displayTouchCoords(int x, int y) { (void)x; (void)y; }

void setAnimation(const char* filename, DisplayIndex display) {
    Atlas& a = (display == DisplayIndex::LEFT) ? g_atlasLeft : g_atlasRight;
    loadAtlasFile(a, filename);
}

void updateLCD() { presentScreen(); }

bool saveScreenshot(const char* path) {
    if (!g_renderer || !g_texture || !path || !path[0]) return false;
    presentScreen();                       // redessine le framebuffer courant
    int w = 0, h = 0;
    if (SDL_GetRendererOutputSize(g_renderer, &w, &h) != 0 || w <= 0 || h <= 0) return false;
    SDL_Surface* surf =
        SDL_CreateRGBSurfaceWithFormat(0, w, h, 32, SDL_PIXELFORMAT_ARGB8888);
    if (!surf) return false;
    const bool read = SDL_RenderReadPixels(g_renderer, nullptr, SDL_PIXELFORMAT_ARGB8888,
                                           surf->pixels, surf->pitch) == 0;
    const bool saved = read && SDL_SaveBMP(surf, path) == 0;
    SDL_FreeSurface(surf);
    if (!saved) std::fprintf(stderr, "[Simulator] capture impossible : %s\n", SDL_GetError());
    return saved;
}

void showCatFace(int leftIndex, int rightIndex) {
    (void)rightIndex;
    if (!g_initialized || !g_sprite240) return;

    const Atlas& src =
        g_atlasLeft.loaded ? g_atlasLeft : (g_atlasRight.loaded ? g_atlasRight : g_atlasLeft);

    std::fill(g_screen.begin(), g_screen.end(), static_cast<uint16_t>(TFT_DARKGREY));

    if (drawFaceToBuffer(g_sprite240, src, leftIndex))
        blitSpriteCentered(g_sprite240);

    if (g_mouseDown && g_mouseX >= 0) drawTouchMarker(g_mouseX, g_mouseY);

    presentScreen();
}

void pushVideo565(DisplayIndex which, const uint16_t* rgb565) {
    (void)which;
    if (!g_initialized || !rgb565) return;
    std::fill(g_screen.begin(), g_screen.end(), static_cast<uint16_t>(TFT_BLACK));
    blitSpriteCentered(rgb565);
    presentScreen();
}

void pushScreen565(const uint16_t* rgb565) {
    if (!g_initialized || !rgb565) return;
    const size_t n = static_cast<size_t>(screenWidth() * screenHeight());
    if (g_screen.size() < n) g_screen.resize(n);
    std::memcpy(g_screen.data(), rgb565, n * sizeof(uint16_t));
    if (g_mouseDown && g_mouseX >= 0) drawTouchMarker(g_mouseX, g_mouseY);
    presentScreen();
}

void loadRobotEyeRes(const char* filename) { (void)filename; }

void showRobotEyes(float normX, float normY, const uint16_t* grid) {
    (void)normX;
    (void)normY;
    (void)grid;
}

bool isRobotEyeResourceReady() { return false; }

bool haveCatStripAtlas() { return g_atlasLeft.loaded || g_atlasRight.loaded; }

int stripColumnCount(DisplayIndex display) {
    const Atlas& a =
        (display == DisplayIndex::LEFT)
            ? g_atlasLeft
            : (g_atlasRight.loaded ? g_atlasRight : g_atlasLeft);
    if (!a.loaded) return 0;
    int cols = a.sheetWidthPx / 240;
    return cols < 1 ? 1 : cols;
}

void reportTimings() {}

bool tftTouchSubsystemReady() { return g_initialized; }

void drawTftTouchFeedback() {
    int16_t x, y;
    if (getIli9341TouchScreenPos(&x, &y)) drawTouchMarker(x, y);
}

bool getIli9341TouchScreenPos(int16_t* outX, int16_t* outY) {
    if (!g_initialized || !outX || !outY) return false;

    const bool latch = g_mousePressedLatch;
    g_mousePressedLatch = false;

    const int rawX = latch ? g_mouseLatchX : g_mouseX;
    const int rawY = latch ? g_mouseLatchY : g_mouseY;
    if (rawX < 0 || rawY < 0) return false;

    int x = screenWidth()  - 1 - rawX;
    int y = screenHeight() - 1 - rawY;
    if (x < 0) x = 0;
    if (y < 0) y = 0;
    if (x >= screenWidth())  x = screenWidth()  - 1;
    if (y >= screenHeight()) y = screenHeight() - 1;
    *outX = static_cast<int16_t>(x);
    *outY = static_cast<int16_t>(y);
    return g_mouseDown || latch;
}

}  // namespace Drivers
