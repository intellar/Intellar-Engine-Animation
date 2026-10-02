cmake_minimum_required(VERSION 3.16)
project(IntellarEngineAnimation VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(MSVC)
    add_compile_options(/W4 /permissive- /utf-8)
else()
    add_compile_options(-Wall -Wextra)
endif()

# --------------------------------------------------------------------------- #
# Library: ISKA reading + animation playback (no dependency on SDL)
# --------------------------------------------------------------------------- #
add_library(intellar_iska STATIC
    src/Iska/IskaLoader.cpp
    src/Iska/IskaPlayer.cpp
    src/Iska/IskaRender.cpp
)
target_include_directories(intellar_iska PUBLIC src)
target_compile_definitions(intellar_iska PRIVATE _CRT_SECURE_NO_WARNINGS)

# --------------------------------------------------------------------------- #
# Simulated screen (SDL2): LCD.h/LCD.cpp vendored from Intellar-Engine-Simulator
# (MIT license, see NOTICE.md). SDL2 is fetched at the first configure.
# --------------------------------------------------------------------------- #
set(SDL_SHARED ON CACHE BOOL "" FORCE)
set(SDL_STATIC OFF CACHE BOOL "" FORCE)
set(SDL_TEST OFF CACHE BOOL "" FORCE)

include(FetchContent)
FetchContent_Declare(
    SDL2
    GIT_REPOSITORY https://github.com/libsdl-org/SDL.git
    GIT_TAG        release-2.28.5
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(SDL2)

add_library(intellar_lcd STATIC third_party/lcd/src/Drivers/LCD.cpp)
target_include_directories(intellar_lcd PUBLIC third_party/lcd/include)
target_compile_definitions(intellar_lcd PUBLIC SDL_MAIN_HANDLED)
target_link_libraries(intellar_lcd PUBLIC SDL2::SDL2)

# --------------------------------------------------------------------------- #
# Demo: 240x320 window + --dump mode (headless BMP/.565 capture)
# --------------------------------------------------------------------------- #
add_executable(intellar_anim_demo demo/main.cpp)
target_compile_definitions(intellar_anim_demo PRIVATE _CRT_SECURE_NO_WARNINGS)
target_link_libraries(intellar_anim_demo PRIVATE intellar_iska intellar_lcd)

# The asset is looked up by a relative path from the run directory: it is copied
# next to the binary, along with SDL2.dll on Windows.
add_custom_command(
    TARGET intellar_anim_demo POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:intellar_anim_demo>/assets
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${CMAKE_CURRENT_SOURCE_DIR}/assets/rabbit3.iska
            $<TARGET_FILE_DIR:intellar_anim_demo>/assets/rabbit3.iska
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:SDL2::SDL2>
            $<TARGET_FILE_DIR:intellar_anim_demo>
    COMMENT "Copy rabbit3.iska + SDL2.dll next to the demo"
)

# --------------------------------------------------------------------------- #
# Offline check: compares the frames rendered by the C++ engine with those of the
# Python tooling (see tools/iska_clip_check.py).
#   cmake --build build --config Release --target iska_clip_check
# --------------------------------------------------------------------------- #
find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
    add_custom_target(iska_clip_check
        COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/iska_clip_check.py
                --iska ${CMAKE_CURRENT_SOURCE_DIR}/assets/rabbit3.iska
                --demo $<TARGET_FILE:intellar_anim_demo>
        DEPENDS intellar_anim_demo
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        COMMENT "C++ vs Python check (pixel-identical frames)"
        VERBATIM
    )
else()
    message(STATUS "Python3 not found: iska_clip_check target disabled")
endif()
