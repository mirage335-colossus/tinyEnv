#ifndef FOUNDATION_SIMPLE_C_SIGNAL_H
#define FOUNDATION_SIMPLE_C_SIGNAL_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

enum { SIMPLE_C_SAMPLE_CAPACITY = 4 };

struct simple_c_state {
    float gain;
    float samples[SIMPLE_C_SAMPLE_CAPACITY];
    size_t count;
};

void simple_c_state_init(struct simple_c_state *state);
size_t simple_c_sample_count(void);
float simple_c_source_sample(size_t index);
float simple_c_apply_gain(float sample, float gain);
int simple_c_collect_sample(struct simple_c_state *state, float sample);

#ifdef __cplusplus
}
#endif
#endif
