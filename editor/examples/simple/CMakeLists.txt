cmake_minimum_required(VERSION 3.24)
project(FoundationEditorSimpleExample LANGUAGES CXX)
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

# Retained generated headers are ordinary build inputs. Building never invokes
# the editor, loads a design JSON document, or discovers a GUI toolkit.
add_executable(foundation-editor-simple main.cpp events.cpp signal.cpp flow_adapter.cpp
  "${FOUNDATION_POLICY_SOURCE_ROOT}/visual/ui/ui.cpp"
  "${FOUNDATION_POLICY_SOURCE_ROOT}/visual/flow/flow.cpp")
target_include_directories(foundation-editor-simple PRIVATE
  "${CMAKE_CURRENT_SOURCE_DIR}" "${FOUNDATION_POLICY_SOURCE_ROOT}")
target_link_libraries(foundation-editor-simple PRIVATE foundation_gui_boundary)
target_compile_features(foundation-editor-simple PRIVATE cxx_std_20)
set_target_properties(foundation-editor-simple PROPERTIES CXX_EXTENSIONS OFF)
foundation_sdk_runtime(foundation-editor-simple)
if(MSVC)
  target_compile_options(foundation-editor-simple PRIVATE /W4 /permissive- /utf-8)
else()
  target_compile_options(foundation-editor-simple PRIVATE -Wall -Wextra -Wpedantic)
endif()

# No installation, package, CI, editor build, SDK extension, or application hook.
