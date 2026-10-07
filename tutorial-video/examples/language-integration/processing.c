#include "processing.h"

/* Ordinary C17 source: an event handler can call this helper. */
float processing_clamp(float sample, float low, float high) {
    if (sample < low) return low;
    if (sample > high) return high;
    return sample;
}
