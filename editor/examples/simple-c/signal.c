#include "signal.h"

/* Ordinary C functions and plain data: no editor or stream-runtime API. */
void simple_c_state_init(struct simple_c_state *state) {
    size_t index;
    state->gain = 2.0f;
    state->count = 0;
    for (index = 0; index < SIMPLE_C_SAMPLE_CAPACITY; ++index)
        state->samples[index] = 0.0f;
}

size_t simple_c_sample_count(void) {
    return 4;
}

float simple_c_source_sample(size_t index) {
    return (float)(index + 1); /* 1, 2, 3, 4 */
}

float simple_c_apply_gain(float sample, float gain) {
    return sample * gain;
}

int simple_c_collect_sample(struct simple_c_state *state, float sample) {
    if (state->count >= SIMPLE_C_SAMPLE_CAPACITY) return 0;
    state->samples[state->count++] = sample;
    return 1;
}
