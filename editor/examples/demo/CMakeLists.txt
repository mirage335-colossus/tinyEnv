cmake_minimum_required(VERSION 3.24)
project(FoundationEditorAdoptionDemo LANGUAGES CXX)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
  message(FATAL_ERROR "Build the demo in a separate build directory")
endif()
get_filename_component(FOUNDATION_POLICY_SOURCE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." REALPATH)
find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
include("${FOUNDATION_POLICY_SOURCE_ROOT}/cmake/BuildPolicy.cmake")
cmake_language(DEFER CALL foundation_finalize_build_policy NO_INSTALL)
include("${FOUNDATION_POLICY_SOURCE_ROOT}/cmake/StaticCxxRuntime.cmake")
include("${FOUNDATION_POLICY_SOURCE_ROOT}/cmake/SdkBuildRuntime.cmake")
include("${FOUNDATION_POLICY_SOURCE_ROOT}/cmake/GuiInputs.cmake")
foundation_gui_inputs()
foundation_gui_headers()

# The application consumes retained normal C++ headers. It does not invoke or
# link the editor model, generator, filesystem/process code or a GUI toolkit.
add_executable(foundation-editor-demo main.cpp handlers.cpp blocks.cpp
  "${FOUNDATION_POLICY_SOURCE_ROOT}/visual/ui/ui.cpp"
  "${FOUNDATION_POLICY_SOURCE_ROOT}/visual/flow/flow.cpp")
target_include_directories(foundation-editor-demo PRIVATE
  "${CMAKE_CURRENT_SOURCE_DIR}" "${FOUNDATION_POLICY_SOURCE_ROOT}")
target_link_libraries(foundation-editor-demo PRIVATE foundation_gui_boundary)
target_compile_features(foundation-editor-demo PRIVATE cxx_std_20)
set_target_properties(foundation-editor-demo PROPERTIES CXX_EXTENSIONS OFF)
foundation_sdk_runtime(foundation-editor-demo)
if(MSVC)
  target_compile_options(foundation-editor-demo PRIVATE /W4 /permissive- /utf-8)
else()
  target_compile_options(foundation-editor-demo PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Optional prebuilt, project-owned Rust C ABI archive. Its construction is a
# separate explicit ordinary compiler command; no Rust tool is discovered here.
set(FOUNDATION_DEMO_RUST_ARCHIVE "" CACHE FILEPATH "Optional existing Rust gain archive")
if(FOUNDATION_DEMO_RUST_ARCHIVE)
  if(NOT EXISTS "${FOUNDATION_DEMO_RUST_ARCHIVE}" OR IS_DIRECTORY "${FOUNDATION_DEMO_RUST_ARCHIVE}")
    message(FATAL_ERROR "FOUNDATION_DEMO_RUST_ARCHIVE must name an existing archive")
  endif()
  add_library(foundation_demo_foreign STATIC IMPORTED)
  set_target_properties(foundation_demo_foreign PROPERTIES IMPORTED_LOCATION "${FOUNDATION_DEMO_RUST_ARCHIVE}")
  target_link_libraries(foundation-editor-demo PRIVATE foundation_demo_foreign)
else()
  target_sources(foundation-editor-demo PRIVATE foreign.cpp)
endif()

# No installation, tests, package, SDK extension or application-build hooks.
