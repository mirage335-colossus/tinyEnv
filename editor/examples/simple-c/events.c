#include "events.h"
#include <stdio.h>

/* Helpers called from C event code can update the same application's widgets. */
int simple_c_show_samples(const struct simple_c_state *state,
                          const struct simple_c_ui *ui) {
    char text[96] = "Output:";
    size_t used = 7;
    size_t index;
    if (state->count > SIMPLE_C_SAMPLE_CAPACITY) return 0;
    for (index = 0; index < state->count; ++index) {
        int written = snprintf(text + used, sizeof text - used,
                               " %.6g", (double)state->samples[index]);
        if (written < 0 || (size_t)written >= sizeof text - used) return 0;
        used += (size_t)written;
    }
    return ui->set_output_text(ui->context, text);
}

int simple_c_on_run(struct simple_c_state *state, const struct simple_c_ui *ui) {
    int half = ui->gain_is_half(ui->context);
    int success;
    if (half < 0) return 0;
    state->gain = half ? 0.5f : 2.0f;
    state->count = 0;
    if (!ui->set_run_enabled(ui->context, 0)) return 0;

    success = ui->set_output_text(ui->context, "Processing...");
    if (success) success = ui->run_samples(ui->context);
    if (success) success = simple_c_show_samples(state, ui);
    if (!success) ui->set_output_text(ui->context, "Processing failed.");
    if (!ui->set_run_enabled(ui->context, 1)) success = 0;
    return success;
}

int simple_c_on_clear(struct simple_c_state *state, const struct simple_c_ui *ui) {
    state->count = 0;
    return ui->set_output_text(ui->context, "Choose a gain, then Run samples.");
}
