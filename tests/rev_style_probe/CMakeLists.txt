cmake_minimum_required(VERSION 3.28)
project(FoundationRevProbe LANGUAGES CXX)

# Four production modules only: no graphics, toolkit dependencies or downloads.
if(NOT IS_DIRECTORY "${FOUNDATION_REV_SOURCE}/source")
    message(FATAL_ERROR "Use tools/rev_probe.py with a verified retained GUI input group")
endif()
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    if(CMAKE_CXX_COMPILER_VERSION VERSION_LESS 15)
        message(FATAL_ERROR "The pinned Rev modules require GCC 15+")
    endif()
elseif(CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
    if(CMAKE_CXX_COMPILER_VERSION VERSION_LESS 19)
        message(FATAL_ERROR "The pinned Rev modules require Clang 19+ and its matching scanner")
    endif()
elseif(MSVC)
    if(MSVC_VERSION LESS 1936)
        message(FATAL_ERROR "The pinned Rev modules require MSVC 19.36+")
    endif()
else()
    message(FATAL_ERROR "Unsupported native Rev module compiler")
endif()
if(CMAKE_CROSSCOMPILING)
    message(FATAL_ERROR "The diagnostic must execute on its native target")
endif()
add_library(foundation_rev_probe STATIC)
target_sources(foundation_rev_probe PUBLIC FILE_SET cxx_modules TYPE CXX_MODULES
    BASE_DIRS "${FOUNDATION_REV_SOURCE}/source" FILES
    "${FOUNDATION_REV_SOURCE}/source/Core/DirtyFlag.ixx"
    "${FOUNDATION_REV_SOURCE}/source/Core/Color.ixx"
    "${FOUNDATION_REV_SOURCE}/source/Core/Resource.ixx"
    "${FOUNDATION_REV_SOURCE}/source/Element/Style/Style.ixx")
target_include_directories(foundation_rev_probe PUBLIC "${FOUNDATION_REV_SOURCE}/external")
target_compile_definitions(foundation_rev_probe PRIVATE PROJECT_ROOT="${FOUNDATION_REV_SOURCE}")
add_executable(foundation_rev_style style.cpp)
target_link_libraries(foundation_rev_style PRIVATE foundation_rev_probe)
foreach(target foundation_rev_probe foundation_rev_style)
    set_target_properties(${target} PROPERTIES CXX_STANDARD 23 CXX_STANDARD_REQUIRED YES
        CXX_EXTENSIONS NO CXX_SCAN_FOR_MODULES ON
        MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    if(MSVC)
        target_compile_options(${target} PRIVATE /utf-8 /permissive-)
    elseif(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
        target_compile_options(${target} PRIVATE -Werror=ambiguous-reversed-operator)
    endif()
endforeach()
enable_testing()
add_test(NAME foundation.rev-probe.equality COMMAND foundation_rev_style equality)
add_test(NAME foundation.rev-probe.layout COMMAND foundation_rev_style layout)
set_tests_properties(foundation.rev-probe.equality foundation.rev-probe.layout PROPERTIES TIMEOUT 20)

# Retain actual selected tools, including the scanner; paths are JSON escaped.
set(identity "{}")
foreach(field CMAKE_CXX_COMPILER CMAKE_CXX_COMPILER_ID CMAKE_CXX_COMPILER_VERSION
        CMAKE_CXX_COMPILER_CLANG_SCAN_DEPS CMAKE_LINKER CMAKE_AR CMAKE_MAKE_PROGRAM
        CMAKE_SYSTEM_NAME CMAKE_SYSTEM_PROCESSOR CMAKE_VERSION)
    string(REPLACE "\\" "\\\\" escaped "${${field}}")
    string(REPLACE "\"" "\\\"" escaped "${escaped}")
    string(JSON identity SET "${identity}" "${field}" "\"${escaped}\"")
endforeach()
file(WRITE "${CMAKE_BINARY_DIR}/compiler.json" "${identity}\n")
