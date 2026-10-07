#pragma once

// A stable, project-owned C ABI crosses the language boundary. Rust is optional
// for this demo and is never required to compile the editor.
extern "C" float foundation_demo_gain(float sample);
extern "C" float foundation_demo_gain_report(float sample, void* context,
                                             void (*report)(void*, float));
