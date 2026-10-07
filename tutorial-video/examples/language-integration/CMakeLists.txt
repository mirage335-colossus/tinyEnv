cmake_minimum_required(VERSION 3.24)
project(TutorialLanguageIntegration LANGUAGES C CXX)

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
  message(FATAL_ERROR "Use a separate build directory")
endif()

# This small example uses an existing native compiler. It downloads nothing.
find_program(TUTORIAL_RUSTC NAMES rustc DOC "Path to an existing native rustc")
if(NOT TUTORIAL_RUSTC)
  message(FATAL_ERROR "Set TUTORIAL_RUSTC to an existing native Rust compiler")
endif()

set(rust_archive "${CMAKE_CURRENT_BINARY_DIR}/${CMAKE_STATIC_LIBRARY_PREFIX}tutorial_processing${CMAKE_STATIC_LIBRARY_SUFFIX}")
add_custom_command(OUTPUT "${rust_archive}"
  COMMAND "${TUTORIAL_RUSTC}" "${CMAKE_CURRENT_SOURCE_DIR}/rust/lib.rs"
    --crate-name tutorial_processing --crate-type staticlib --edition 2021
    -C panic=abort -C opt-level=2 -o "${rust_archive}"
  DEPENDS rust/lib.rs rust/gain.rs rust/smoother.rs
  COMMENT "Compiling Rust gain and smoother modules" VERBATIM)
add_custom_target(tutorial-rust-archive DEPENDS "${rust_archive}")
add_library(tutorial_rust STATIC IMPORTED)
set_target_properties(tutorial_rust PROPERTIES IMPORTED_LOCATION "${rust_archive}")
add_dependencies(tutorial_rust tutorial-rust-archive)

add_executable(tutorial-integration)
# Add new C/C++ translation units here. Headers do not compile on their own.
target_sources(tutorial-integration PRIVATE app.cpp processing.c display.cpp)
target_compile_features(tutorial-integration PRIVATE c_std_17 cxx_std_20)
set_target_properties(tutorial-integration PROPERTIES
  C_EXTENSIONS OFF CXX_EXTENSIONS OFF)
target_link_libraries(tutorial-integration PRIVATE tutorial_rust)
if(MSVC)
  target_compile_options(tutorial-integration PRIVATE /W4)
else()
  target_compile_options(tutorial-integration PRIVATE -Wall -Wextra -Wpedantic)
endif()

enable_testing()
add_test(NAME language-integration COMMAND tutorial-integration)
