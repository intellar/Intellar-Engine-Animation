#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#include "IskaFormat.h"

/** Loading and validation of an `.iska` file (see IskaFormat.h). */
namespace Iska {

/** Loads an .iska from a file. `error` receives the reason when it fails. */
bool loadAsset(const char* path, Asset& out, std::string* error = nullptr);

/** Loads an .iska from a memory buffer (handy for embedded assets). */
bool parseAsset(const uint8_t* data, size_t size, Asset& out,
                std::string* error = nullptr);

/** Readable summary of an asset (one line for the bones, one per animation). */
std::string describe(const Asset& asset);

}  // namespace Iska
