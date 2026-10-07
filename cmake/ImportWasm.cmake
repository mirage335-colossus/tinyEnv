# Optional assembly bridge: reuse a verified browser build without compiling it
# in each native target graph. Configure, selected builds, install and CPack all
# revalidate the same pinned application/source identity.
include_guard(GLOBAL)
set(FOUNDATION_WASM_PACKAGE "" CACHE PATH "Complete prebuilt offline Wasm package directory")
set(FOUNDATION_WASM_PACKAGE_SHA256 "" CACHE STRING "Exact web-manifest.json SHA-256")
if(NOT FOUNDATION_WASM_PACKAGE AND NOT FOUNDATION_WASM_PACKAGE_SHA256)
  return()
endif()
if(EMSCRIPTEN OR NOT FOUNDATION_WASM_PACKAGE OR NOT FOUNDATION_WASM_PACKAGE_SHA256)
  message(FATAL_ERROR "Native Wasm import requires both FOUNDATION_WASM_PACKAGE and FOUNDATION_WASM_PACKAGE_SHA256")
endif()
get_filename_component(FOUNDATION_WASM_PACKAGE "${FOUNDATION_WASM_PACKAGE}" REALPATH)
set(foundation_wasm_stage "${CMAKE_BINARY_DIR}/imported-wasm")
foreach(value "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}" "${FOUNDATION_WASM_PACKAGE}"
    "${FOUNDATION_WASM_PACKAGE_SHA256}" "${foundation_wasm_stage}")
  string(FIND "${value}" "]========]" bracket_end)
  if(NOT bracket_end EQUAL -1 OR value MATCHES "[;\n\r]")
    message(FATAL_ERROR "Unsupported control/list delimiter in Wasm import path")
  endif()
endforeach()
set(foundation_wasm_command "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/import_wasm.py"
  --package "${FOUNDATION_WASM_PACKAGE}" --sha256 "${FOUNDATION_WASM_PACKAGE_SHA256}"
  --source-root "${CMAKE_SOURCE_DIR}" --output "${foundation_wasm_stage}")
execute_process(COMMAND ${foundation_wasm_command} COMMAND_ERROR_IS_FATAL ANY)
add_custom_target(foundation-wasm-import ALL COMMAND ${foundation_wasm_command} VERBATIM)
if(TARGET foundation_core)
  add_dependencies(foundation_core foundation-wasm-import)
else()
  message(FATAL_ERROR "Include ImportWasm after foundation_core and Python3 are available")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  "${FOUNDATION_WASM_PACKAGE}/web-manifest.json" "${FOUNDATION_WASM_PACKAGE}/manifest.sha256"
  "${FOUNDATION_WASM_PACKAGE}/software-foundation-wasm.html")
configure_file("${CMAKE_CURRENT_LIST_DIR}/InstallWasm.cmake.in"
  "${CMAKE_BINARY_DIR}/InstallWasm.cmake" @ONLY)
# Runs before copying installed bytes, including direct cmake --install and CPack.
install(SCRIPT "${CMAKE_BINARY_DIR}/InstallWasm.cmake")
install(FILES "${foundation_wasm_stage}/package/software-foundation-wasm.html"
  "${foundation_wasm_stage}/package/web-manifest.json"
  "${foundation_wasm_stage}/package/manifest.sha256"
  DESTINATION "${CMAKE_INSTALL_DATADIR}/software-foundation/wasm")
install(FILES "${foundation_wasm_stage}/open-offline.cmd"
  DESTINATION "${CMAKE_INSTALL_DATADIR}/software-foundation")
install(PROGRAMS "${foundation_wasm_stage}/open-offline.sh"
  DESTINATION "${CMAKE_INSTALL_DATADIR}/software-foundation")
