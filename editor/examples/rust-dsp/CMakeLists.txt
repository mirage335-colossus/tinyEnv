cmake_minimum_required(VERSION 3.24)
project(FoundationEditorRustDspExample LANGUAGES CXX)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
  message(FATAL_ERROR "Build the example in a separate build directory")
endif()
get_filename_component(FOUNDATION_POLICY_SOURCE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." REALPATH)
find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
include("${FOUNDATION_POLICY_SOURCE_ROOT}/cmake/BuildPolicy.cmake")
cmake_language(DEFER CALL foundation_finalize_build_policy NO_INSTALL)
include("${FOUNDATION_POLICY_SOURCE_ROOT}/cmake/StaticCxxRuntime.cmake")
include("${FOUNDATION_POLICY_SOURCE_ROOT}/cmake/SdkBuildRuntime.cmake")

# The Rust dependency belongs only to this optional project. These normal build
# rules compile ordinary source with an existing compiler, without Cargo/network.
set(FOUNDATION_RUST_DSP_ARCHIVE "" CACHE FILEPATH "Optional existing target-matched Rust DSP archive")
if(FOUNDATION_RUST_DSP_ARCHIVE)
  if(NOT EXISTS "${FOUNDATION_RUST_DSP_ARCHIVE}" OR
     IS_DIRECTORY "${FOUNDATION_RUST_DSP_ARCHIVE}")
    message(FATAL_ERROR "FOUNDATION_RUST_DSP_ARCHIVE must name an existing archive")
  endif()
  set(rust_archive "${FOUNDATION_RUST_DSP_ARCHIVE}")
else()
  find_program(FOUNDATION_RUST_DSP_RUSTC NAMES rustc
    DOC "Existing native Rust compiler; use an absolute path to retained rustc")
  if(NOT FOUNDATION_RUST_DSP_RUSTC)
    message(FATAL_ERROR "This optional Rust example needs existing rustc; set FOUNDATION_RUST_DSP_RUSTC. The editor does not need Rust.")
  endif()
  set(rust_archive "${CMAKE_CURRENT_BINARY_DIR}/${CMAKE_STATIC_LIBRARY_PREFIX}foundation_rust_dsp${CMAKE_STATIC_LIBRARY_SUFFIX}")
  add_custom_command(OUTPUT "${rust_archive}"
    COMMAND "${FOUNDATION_RUST_DSP_RUSTC}" "${CMAKE_CURRENT_SOURCE_DIR}/dsp.rs"
      --crate-name foundation_rust_dsp --crate-type staticlib --edition 2021
      -C panic=abort -C opt-level=2 -o "${rust_archive}"
    DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/dsp.rs"
    COMMENT "Compiling ordinary Rust FIR source" VERBATIM)
  add_custom_target(foundation-rust-dsp-archive DEPENDS "${rust_archive}")
endif()
add_library(foundation_rust_dsp STATIC IMPORTED)
set_target_properties(foundation_rust_dsp PROPERTIES
  IMPORTED_LOCATION "${rust_archive}")
if(TARGET foundation-rust-dsp-archive)
  add_dependencies(foundation_rust_dsp foundation-rust-dsp-archive)
endif()

add_executable(foundation-editor-rust-dsp main.cpp flow_adapter.cpp
  "${FOUNDATION_POLICY_SOURCE_ROOT}/visual/flow/flow.cpp")
target_include_directories(foundation-editor-rust-dsp PRIVATE
  "${CMAKE_CURRENT_SOURCE_DIR}" "${FOUNDATION_POLICY_SOURCE_ROOT}")
target_compile_features(foundation-editor-rust-dsp PRIVATE cxx_std_20)
set_target_properties(foundation-editor-rust-dsp PROPERTIES CXX_EXTENSIONS OFF)
target_link_libraries(foundation-editor-rust-dsp PRIVATE foundation_rust_dsp)
foundation_sdk_runtime(foundation-editor-rust-dsp)
if(MSVC)
  target_compile_options(foundation-editor-rust-dsp PRIVATE /W4 /permissive- /utf-8)
else()
  target_compile_options(foundation-editor-rust-dsp PRIVATE -Wall -Wextra -Wpedantic)
endif()

# No installation, CTest inventory, SDK extension or application-build hooks.
