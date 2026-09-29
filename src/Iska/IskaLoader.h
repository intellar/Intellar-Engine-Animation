#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#include "IskaFormat.h"

/** Chargement et validation d'un fichier `.iska` (voir IskaFormat.h). */
namespace Iska {

/** Charge un .iska depuis un fichier. `error` recoit le motif en cas d'echec. */
bool loadAsset(const char* path, Asset& out, std::string* error = nullptr);

/** Charge un .iska depuis un tampon memoire (utile pour les assets embarques). */
bool parseAsset(const uint8_t* data, size_t size, Asset& out,
                std::string* error = nullptr);

/** Resume lisible d'un asset (une ligne pour les os, une par animation). */
std::string describe(const Asset& asset);

}  // namespace Iska
