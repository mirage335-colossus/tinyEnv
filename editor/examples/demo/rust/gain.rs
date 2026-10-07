#![no_std]

// No Cargo crates, generated binding tool, allocator or editor dependency.
// The C++ application chooses this symbol through its normal link graph.
#[no_mangle]
pub extern "C" fn foundation_demo_gain(sample: f32) -> f32 {
    sample * 2.0
}

#[no_mangle]
pub extern "C" fn foundation_demo_gain_report(
    sample: f32,
    context: *mut core::ffi::c_void,
    report: Option<unsafe extern "C" fn(*mut core::ffi::c_void, f32)>,
) -> f32 {
    let result = foundation_demo_gain(sample);
    if let Some(callback) = report {
        // The C++ caller owns context through this synchronous call and promises
        // the callback cannot unwind across the ABI boundary.
        unsafe { callback(context, result) };
    }
    result
}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo<'_>) -> ! {
    // A panic cannot unwind across the C ABI. The ordinary native C runtime
    // provides abort; the scalar demonstration itself has no panicking paths.
    extern "C" { fn abort() -> !; }
    unsafe { abort() }
}
