#include "signal.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static int require_close(float actual, float expected, const char *label) {
    if (!isfinite(actual) || fabsf(actual - expected) > 0.000001f) {
        fprintf(stderr, "%s: expected %.3f, got %.3f\n", label, expected, actual);
        return 0;
    }
    return 1;
}

int main(int argc, char **argv) {
    struct simple_c_state state;
    char *end = NULL;
    float offset;
    size_t index;

    if (argc != 2) {
        fprintf(stderr, "Usage: algorithm-check EXPECTED_OFFSET\n");
        return 2;
    }
    offset = strtof(argv[1], &end);
    if (end == argv[1] || *end != '\0' || !isfinite(offset)) return 2;

    simple_c_state_init(&state);
    if (state.count != 0 || state.gain != 2.0f || simple_c_sample_count() != 4) {
        fprintf(stderr, "Unexpected initial state or sample count\n");
        return 1;
    }
    for (index = 0; index < SIMPLE_C_SAMPLE_CAPACITY; ++index) {
        const float input = simple_c_source_sample(index);
        const float output = simple_c_apply_gain(input, state.gain);
        if (!require_close(state.samples[index], 0.0f, "Initial buffer") ||
            !require_close(input, (float)(index + 1), "Input sample") ||
            !require_close(output, (float)(2 * (index + 1)) + offset, "Gain result") ||
            !simple_c_collect_sample(&state, output)) return 1;
    }
    if (state.count != SIMPLE_C_SAMPLE_CAPACITY ||
        simple_c_collect_sample(&state, 99.0f) ||
        state.count != SIMPLE_C_SAMPLE_CAPACITY) {
        fprintf(stderr, "Collection did not respect buffer capacity\n");
        return 1;
    }
    if (!require_close(simple_c_apply_gain(-2.0f, 2.0f), -4.0f + offset,
                       "Negative sample") ||
        !require_close(simple_c_apply_gain(7.0f, 0.0f), offset, "Zero gain"))
        return 1;

    printf("Inputs: [1, 2, 3, 4]\nGain: 2\nOutputs: [");
    for (index = 0; index < state.count; ++index)
        printf("%s%.0f", index ? ", " : "", state.samples[index]);
    printf("]\nAlgorithm check: PASS\n");
    return 0;
}
