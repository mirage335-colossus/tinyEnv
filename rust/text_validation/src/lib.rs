#![cfg_attr(not(test), no_std)]
#![deny(unsafe_op_in_unsafe_fn)]

const MAX_TEXT_BYTES: usize = 256;
const OK: u32 = 0;
const INVALID_LENGTH: u32 = 1;
const INVALID_ASCII: u32 = 2;
const INVALID_POINTER: u32 = 3;
const PROVIDER_RUST: u32 = 1;

fn validate_text(bytes: &[u8]) -> u32 {
    if bytes.is_empty() || bytes.len() > MAX_TEXT_BYTES {
        return INVALID_LENGTH;
    }
    if bytes.iter().any(|&byte| byte < 32 || byte > 126) {
        return INVALID_ASCII;
    }
    OK
}

/// Validate the private v1 text format without retaining or modifying its bytes.
///
/// # Safety
/// For lengths 1..256, a nonnull pointer must address `length` initialized bytes
/// in one live allocation, unchanged for the duration of this call. Length errors
/// and null pointers are rejected before forming a slice or accessing any byte.
#[no_mangle]
pub unsafe extern "C" fn foundation_text_validate_v1(bytes: *const u8, length: usize) -> u32 {
    if length == 0 || length > MAX_TEXT_BYTES {
        return INVALID_LENGTH;
    }
    if bytes.is_null() {
        return INVALID_POINTER;
    }
    // The length is bounded and nonzero; the caller supplies the live allocation
    // and prevents mutation until return. The borrowed slice stays within this call.
    let text = unsafe { core::slice::from_raw_parts(bytes, length) };
    validate_text(text)
}

#[no_mangle]
pub extern "C" fn foundation_text_provider_v1() -> u32 {
    PROVIDER_RUST
}

#[cfg(not(test))]
extern "C" {
    fn foundation_rust_panic() -> !;
}

#[cfg(not(test))]
#[panic_handler]
fn panic(_info: &core::panic::PanicInfo<'_>) -> ! {
    // The host hook has no arguments, never returns, and cannot unwind into Rust.
    unsafe { foundation_rust_panic() }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_vectors_keep_the_text_contract() {
        assert_eq!(validate_text(b" "), OK);
        assert_eq!(validate_text(b"~"), OK);
        assert_eq!(validate_text(b"Alpha 123 !~"), OK);
        assert_eq!(validate_text(b""), INVALID_LENGTH);
        assert_eq!(validate_text(&[b'x'; 257]), INVALID_LENGTH);
        assert_eq!(validate_text(&[0; 257]), INVALID_LENGTH);
        for text in [&b"bad\ntext"[..], &b"\0"[..], &b"\x1f"[..], &b"\x7f"[..], &b"\xff"[..]] {
            assert_eq!(validate_text(text), INVALID_ASCII);
        }
    }

    #[test]
    fn every_single_byte_has_the_expected_status() {
        for value in 0..=255u8 {
            let expected = match value {
                32..=126 => OK,
                _ => INVALID_ASCII,
            };
            assert_eq!(validate_text(&[value]), expected, "byte {}", value);
        }
    }

    #[test]
    fn every_allowed_length_is_accepted() {
        let bytes = [b'x'; MAX_TEXT_BYTES];
        for length in 1..=MAX_TEXT_BYTES {
            assert_eq!(validate_text(&bytes[..length]), OK);
        }
    }

    #[test]
    fn invalid_bytes_are_found_at_every_position() {
        let mut bytes = [b' '; MAX_TEXT_BYTES];
        for position in 0..MAX_TEXT_BYTES {
            for invalid in [0, 31, 127, 128, 255] {
                bytes[position] = invalid;
                assert_eq!(validate_text(&bytes), INVALID_ASCII);
            }
            bytes[position] = b' ';
        }
        assert_eq!(validate_text(&bytes), OK);
    }

    #[test]
    fn ffi_checks_bounds_and_null_before_borrowing() {
        let dangling = core::ptr::NonNull::<u8>::dangling().as_ptr();
        for pointer in [core::ptr::null(), dangling as *const u8] {
            for length in [0, 257, usize::MAX] {
                // Invalid lengths promise not to inspect even a dangling pointer.
                assert_eq!(unsafe { foundation_text_validate_v1(pointer, length) }, INVALID_LENGTH);
            }
        }
        for length in [1, 256] {
            assert_eq!(unsafe { foundation_text_validate_v1(core::ptr::null(), length) }, INVALID_POINTER);
        }
        let mut bytes = [b'~'; MAX_TEXT_BYTES];
        let valid_bytes = bytes;
        assert_eq!(unsafe { foundation_text_validate_v1(bytes.as_ptr(), bytes.len()) }, OK);
        assert_eq!(bytes, valid_bytes);
        bytes[MAX_TEXT_BYTES - 1] = 127;
        let invalid_bytes = bytes;
        assert_eq!(unsafe { foundation_text_validate_v1(bytes.as_ptr(), bytes.len()) }, INVALID_ASCII);
        assert_eq!(bytes, invalid_bytes);
    }

    #[test]
    fn ffi_identifies_the_actual_rust_provider() {
        assert_eq!(foundation_text_provider_v1(), 1);
    }
}
