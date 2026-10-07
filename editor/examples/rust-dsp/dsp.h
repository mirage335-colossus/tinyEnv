#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
static_assert(sizeof(float) == 4, "Rust f32 interoperability requires a four-byte C++ float");
#endif

// Layout matches dsp.rs. Zero initialization starts a new independent stream.
typedef struct FoundationRustDspState {
    float newer;
    float older;
    uint32_t phase;
} FoundationRustDspState;

typedef struct FoundationRustDspResult {
    size_t consumed;
    size_t produced;
    int32_t status;
} FoundationRustDspResult;

#ifdef __cplusplus
extern "C" {
#endif
// Disjoint aligned storage is valid for the call; no pointers are retained.
// Null input/output is permitted only when its length/capacity is zero.
// Status 0: success, possibly partial because output is full. Status 1: invalid
// null pointer, oversized length, or phase; counts are zero and state is intact.
FoundationRustDspResult foundation_rust_dsp_process(
    FoundationRustDspState* state, const float* input, size_t input_count,
    float* output, size_t output_capacity);
#ifdef __cplusplus
}
#endif
