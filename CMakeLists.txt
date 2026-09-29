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
# Bibliotheque : lecture + lecture d'animations ISKA (aucune dependance a SDL)
# --------------------------------------------------------------------------- #
add_library(intellar_iska STATIC
    src/Iska/IskaLoader.cpp
    src/Iska/IskaPlayer.cpp
    src/Iska/IskaRender.cpp
)
target_include_directories(intellar_iska PUBLIC src)
target_compile_definitions(intellar_iska PRIVATE _CRT_SECURE_NO_WARNINGS)

# --------------------------------------------------------------------------- #
# Ecran simule (SDL2) : LCD.h/LCD.cpp vendores depuis Intellar-Engine-Simulator
# (licence MIT, voir NOTICE.md). SDL2 est recupere au premier configure.
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
# Demo : fenetre 240x320 + mode --dump (capture BMP/.565 sans fenetre)
# --------------------------------------------------------------------------- #
add_executable(intellar_anim_demo demo/main.cpp)
target_compile_definitions(intellar_anim_demo PRIVATE _CRT_SECURE_NO_WARNINGS)
target_link_libraries(intellar_anim_demo PRIVATE intellar_iska intellar_lcd)

# L'asset est cherche en chemin relatif depuis le repertoire d'execution : on le
# copie donc a cote du binaire, ainsi que SDL2.dll sous Windows.
add_custom_command(
    TARGET intellar_anim_demo POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:intellar_anim_demo>/assets
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${CMAKE_CURRENT_SOURCE_DIR}/assets/rabbit3.iska
            $<TARGET_FILE_DIR:intellar_anim_demo>/assets/rabbit3.iska
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:SDL2::SDL2>
            $<TARGET_FILE_DIR:intellar_anim_demo>
    COMMENT "Copie rabbit3.iska + SDL2.dll a cote de la demo"
)

# --------------------------------------------------------------------------- #
# Verification hors ligne : compare les images rendues par le moteur C++ a
# celles de l'outillage Python (voir tools/iska_clip_check.py).
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
        COMMENT "Verification C++ vs Python (images identiques au pixel pres)"
        VERBATIM
    )
else()
    message(STATUS "Python3 introuvable : cible iska_clip_check desactivee")
endif()
