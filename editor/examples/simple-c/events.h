#ifndef FOUNDATION_SIMPLE_C_EVENTS_H
#define FOUNDATION_SIMPLE_C_EVENTS_H

#include "signal.h"

#ifdef __cplusplus
extern "C" {
#endif

/* The application owns context and initialized state and supplies every callback.
   Callbacks are synchronous; strings
   need remain valid only during the call. No callback retains these pointers.
   Mutation callbacks return 1 on success, 0 on failure. gain_is_half returns
   1 for half, 0 otherwise, and -1 on error.
   The C++ bridge catches exceptions before they reach this C code. */
struct simple_c_ui {
    void *context;
    int (*gain_is_half)(void *context);
    int (*set_run_enabled)(void *context, int enabled);
    int (*set_output_text)(void *context, const char *text);
    int (*run_samples)(void *context);
};

int simple_c_show_samples(const struct simple_c_state *state,
                          const struct simple_c_ui *ui);
int simple_c_on_run(struct simple_c_state *state, const struct simple_c_ui *ui);
int simple_c_on_clear(struct simple_c_state *state, const struct simple_c_ui *ui);

#ifdef __cplusplus
}
#endif
#endif
