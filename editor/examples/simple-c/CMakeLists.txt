cmake_minimum_required(VERSION 3.24)
project(FoundationEditorSimpleCExample LANGUAGES C CXX)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
  message(FATAL_ERROR "Build the example in a separate build directory")
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

# CMake compiles these .c files with the C compiler, as ordinary C17.
add_library(simple-c-behavior STATIC signal.c events.c)
target_compile_features(simple-c-behavior PRIVATE c_std_17)
set_target_properties(simple-c-behavior PROPERTIES C_EXTENSIONS OFF)

# Retained generated headers are ordinary application inputs. No editor,
# design JSON, GUI toolkit, Rust compiler or download participates in this build.
add_executable(foundation-editor-simple-c main.cpp event_adapter.cpp flow_adapter.cpp
  "${FOUNDATION_POLICY_SOURCE_ROOT}/visual/ui/ui.cpp"
  "${FOUNDATION_POLICY_SOURCE_ROOT}/visual/flow/flow.cpp")
target_include_directories(foundation-editor-simple-c PRIVATE
  "${CMAKE_CURRENT_SOURCE_DIR}" "${FOUNDATION_POLICY_SOURCE_ROOT}")
target_link_libraries(foundation-editor-simple-c PRIVATE simple-c-behavior foundation_gui_boundary)
target_compile_features(foundation-editor-simple-c PRIVATE cxx_std_20)
set_target_properties(foundation-editor-simple-c PROPERTIES CXX_EXTENSIONS OFF)
foundation_sdk_runtime(foundation-editor-simple-c)
foreach(target simple-c-behavior foundation-editor-simple-c)
  if(MSVC)
    target_compile_options(${target} PRIVATE /W4 /utf-8)
  else()
    target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
  endif()
endforeach()
if(MSVC)
  target_compile_options(foundation-editor-simple-c PRIVATE /permissive-)
endif()

# No installation, package, CI, editor-build or application-build hook.
