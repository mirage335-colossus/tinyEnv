#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdlib>
#ifdef FOUNDATION_GUI_SDL_ENTRY
#include <SDL.h>
#endif

int foundation_gui_main(int argc, char** argv);

// Both the Microsoft CRT and MinGW initialize these before invoking WinMain.
// The embedded UTF-8 manifest keeps their narrow arguments consistent with the
// application's existing UTF-8 command-line contract.
int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int) {
#ifdef FOUNDATION_GUI_SDL_ENTRY
    SDL_SetMainReady();
#endif
    return foundation_gui_main(__argc, __argv);
}
#endif
