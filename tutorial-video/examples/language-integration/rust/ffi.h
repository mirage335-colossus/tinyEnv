#ifndef TUTORIAL_RUST_FFI_H
#define TUTORIAL_RUST_FFI_H

#ifdef __cplusplus
extern "C" {
#endif

float tutorial_rust_gain(float sample, float gain);
float tutorial_rust_smooth(float previous, float sample, float alpha);

#ifdef __cplusplus
}
#endif

#endif
