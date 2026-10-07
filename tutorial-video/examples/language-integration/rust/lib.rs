#![no_std]

mod gain;
mod smoother; // Add a Rust source file by declaring its module.

// Scalar C ABI: no ownership, references, or Rust containers cross the boundary.
#[no_mangle]
pub extern "C" fn tutorial_rust_gain(sample: f32, factor: f32) -> f32 {
    gain::apply(sample, factor)
}

#[no_mangle]
pub extern "C" fn tutorial_rust_smooth(previous: f32, sample: f32, alpha: f32) -> f32 {
    smoother::apply(previous, sample, alpha)
}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo<'_>) -> ! {
    // Keep panic unwinding out of the C ABI. The native C runtime provides abort.
    extern "C" { fn abort() -> !; }
    unsafe { abort() }
}
