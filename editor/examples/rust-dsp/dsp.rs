#![no_std]

// Ordinary Rust signal processing. No Cargo crates, allocator or editor API.
// The caller owns one state per stream and keeps it across successive chunks.
#[repr(C)]
pub struct FilterState {
    pub newer: f32,
    pub older: f32,
    pub phase: u32,
}

#[repr(C)]
pub struct ProcessResult {
    pub consumed: usize,
    pub produced: usize,
    pub status: i32,
}

// A causal three-tap FIR [1/4, 1/2, 1/4], followed by decimation by two.
// Zero-initialized state supplies the initial history. Produce samples for the
// second, fourth, ... inputs. Do not consume an output-due sample unless there
// is room for its result. Chunk boundaries never reset history or phase.
pub fn process_samples(
    state: &mut FilterState,
    input: &[f32],
    output: &mut [f32],
) -> ProcessResult {
    let mut consumed = 0;
    let mut produced = 0;
    for &sample in input {
        let output_due = state.phase == 1;
        let filtered = 0.25 * sample + 0.5 * state.newer + 0.25 * state.older;
        if output_due {
            let destination = match output.get_mut(produced) {
                Some(destination) => destination,
                None => break,
            };
            *destination = filtered;
            produced += 1;
        }
        state.older = state.newer;
        state.newer = sample;
        state.phase ^= 1;
        consumed += 1;
    }
    ProcessResult { consumed, produced, status: 0 }
}

// The small C ABI boundary lets normal C++ code call the Rust algorithm.
// The caller must provide aligned, live, non-overlapping state/input/output
// storage, with these lengths, and exclusive access to state and output during
// the call. Pointers may be null only for a zero-length input or output.
// Success is status 0; status 1 rejects null, oversized, or invalid-phase input
// without changing state/output. No Rust borrow or buffer survives this call.
#[no_mangle]
pub unsafe extern "C" fn foundation_rust_dsp_process(
    state: *mut FilterState,
    input: *const f32,
    input_count: usize,
    output: *mut f32,
    output_capacity: usize,
) -> ProcessResult {
    let invalid = ProcessResult { consumed: 0, produced: 0, status: 1 };
    let maximum = isize::MAX as usize / core::mem::size_of::<f32>();
    if state.is_null()
        || (input_count != 0 && input.is_null())
        || (output_capacity != 0 && output.is_null())
        || input_count > maximum
        || output_capacity > maximum
    {
        return invalid;
    }
    let state = &mut *state;
    if state.phase > 1 {
        return invalid;
    }
    // Even an empty Rust slice needs a non-null aligned pointer. Use ordinary
    // empty slices for zero lengths rather than borrowing a possibly null one.
    let input = if input_count == 0 { &[] } else {
        core::slice::from_raw_parts(input, input_count)
    };
    let output = if output_capacity == 0 { &mut [] } else {
        core::slice::from_raw_parts_mut(output, output_capacity)
    };
    process_samples(state, input, output)
}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo<'_>) -> ! {
    // Unwinding cannot cross this ABI. The native C runtime supplies abort.
    extern "C" { fn abort() -> !; }
    unsafe { abort() }
}
