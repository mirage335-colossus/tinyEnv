include_guard(GLOBAL)

# Target sysroot directories are compiler inputs, never runtime loader paths:
# adding one to RPATH could load the SDK libc into an ordinary host process.
if(FOUNDATION_SDK_ROOT AND CMAKE_SYSTEM_NAME STREQUAL "Linux")
  foreach(language C CXX)
    foreach(directory lib lib64 usr/lib usr/lib64)
      list(APPEND CMAKE_${language}_IMPLICIT_LINK_DIRECTORIES "${CMAKE_SYSROOT}/${directory}")
    endforeach()
    list(REMOVE_DUPLICATES CMAKE_${language}_IMPLICIT_LINK_DIRECTORIES)
  endforeach()
endif()

function(foundation_sdk_runtime target)
  if(NOT FOUNDATION_SDK_ROOT OR NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    return()
  endif()
  if(NOT FOUNDATION_PORTABLE)
    get_property(checked GLOBAL PROPERTY FOUNDATION_SDK_STATIC_RUNTIME_CHECKED)
    if(NOT checked)
      foundation_require_static_gnu_runtime()
      set_property(GLOBAL PROPERTY FOUNDATION_SDK_STATIC_RUNTIME_CHECKED TRUE)
    endif()
    foundation_link_static_gnu_runtime(${target} PRIVATE)
  endif()
  get_target_property(type "${target}" TYPE)
  if(NOT type STREQUAL "EXECUTABLE")
    return()
  endif()
  if(NOT target MATCHES "^[A-Za-z0-9_][A-Za-z0-9_.+-]*$")
    message(FATAL_ERROR "Unsafe SDK runtime target name: ${target}")
  endif()
  get_target_property(registered "${target}" FOUNDATION_SDK_RUNTIME)
  if(registered)
    message(FATAL_ERROR "SDK runtime already registered: ${target}")
  endif()
  set_property(TARGET "${target}" PROPERTY FOUNDATION_SDK_RUNTIME TRUE)
  # Build with CMake's install-RPATH encoder to avoid editable build-RPATH
  # padding and older Ninja generators' manual LINKER:$ORIGIN escaping bug.
  # Finalization below preserves the caller's installed policy before selecting
  # the exact private build path. Only installed copies need a path rewrite.
  # DT_RPATH is inherited by indirect private dependencies.
  target_link_options(${target} PRIVATE "LINKER:--disable-new-dtags")
  set_target_properties(${target} PROPERTIES SKIP_BUILD_RPATH TRUE
    BUILD_WITH_INSTALL_RPATH TRUE)
  set_property(GLOBAL APPEND PROPERTY FOUNDATION_SDK_ALL_RUNTIME_TARGETS "${target}")
  set_property(DIRECTORY APPEND PROPERTY FOUNDATION_SDK_RUNTIME_TARGETS "${target}")
  get_property(scheduled DIRECTORY PROPERTY FOUNDATION_SDK_RUNTIME_SCHEDULED)
  if(NOT scheduled)
    set_property(DIRECTORY PROPERTY FOUNDATION_SDK_RUNTIME_SCHEDULED TRUE)
    cmake_language(DEFER CALL _foundation_finalize_sdk_runtime)
  endif()
endfunction()

# These literals enter generated installation code. Spaces remain supported;
# reject CMake expansion/quoting/list syntax instead of interpreting it later.
function(_foundation_sdk_install_literal value description)
  if(value MATCHES "[\"\\\\;$\n\r]")
    message(FATAL_ERROR "Unsupported metacharacter in SDK ${description}")
  endif()
endfunction()

function(_foundation_finalize_sdk_runtime)
  get_property(targets DIRECTORY PROPERTY FOUNDATION_SDK_RUNTIME_TARGETS)
  file(SHA256 "${FOUNDATION_SDK_ROOT}/sdk.json" manifest)
  set(helper "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../tools/sdk_build_runtime.py")
  foreach(target IN LISTS targets)
    # Read the final policy after foundation_options and caller overrides. With
    # CMake's padding disabled, installation may shorten this string but cannot
    # grow it. Fail at configuration rather than truncate or rewrite build bytes.
    get_target_property(install_rpath "${target}" INSTALL_RPATH)
    if(NOT install_rpath)
      set(install_rpath "")
    endif()
    string(REPLACE ";" ":" install_rpath "${install_rpath}")
    string(LENGTH "${install_rpath}" install_length)
    string(LENGTH "$ORIGIN/.sdk-runtime/${target}" build_length)
    if(install_rpath MATCHES "\\$<" OR install_length GREATER build_length)
      message(FATAL_ERROR "SDK installed RPATH for ${target} must be a literal no longer than its private build RPATH")
    endif()
    string(REPLACE "$ORIGIN" "" literal_rpath "${install_rpath}")
    _foundation_sdk_install_literal("${literal_rpath}" "installed RPATH")
    set(configurations DEBUG RELEASE RELWITHDEBINFO MINSIZEREL ${CMAKE_CONFIGURATION_TYPES} ${CMAKE_BUILD_TYPE})
    set(name_properties OUTPUT_NAME RUNTIME_OUTPUT_NAME PREFIX SUFFIX)
    foreach(configuration IN LISTS configurations)
      string(TOUPPER "${configuration}" configuration)
      list(APPEND name_properties "OUTPUT_NAME_${configuration}" "RUNTIME_OUTPUT_NAME_${configuration}" "${configuration}_POSTFIX")
    endforeach()
    foreach(property IN LISTS name_properties)
      get_target_property(value "${target}" "${property}")
      if(value)
        _foundation_sdk_install_literal("${value}" "executable name")
      endif()
    endforeach()
    set_target_properties(${target} PROPERTIES FOUNDATION_SDK_INSTALL_RPATH "${install_rpath}"
      INSTALL_RPATH "$ORIGIN/.sdk-runtime/${target}" INSTALL_RPATH_USE_LINK_PATH FALSE)
    # Components do not create a dependency under CMP0112 NEW (CMake >=3.24).
    # TARGET_FILE here would create a target/guard dependency cycle.
    add_custom_target("foundation-sdk-runtime-${target}"
      COMMAND "${Python3_EXECUTABLE}" -B "${helper}" --guard
        --sdk "${FOUNDATION_SDK_ROOT}" --manifest-sha256 "${manifest}"
        --executable "$<TARGET_FILE_DIR:${target}>/$<TARGET_FILE_NAME:${target}>"
        --target "${target}" --processor "${CMAKE_SYSTEM_PROCESSOR}"
      COMMENT "Checking SDK development runtime for ${target}" VERBATIM)
    add_dependencies("${target}" "foundation-sdk-runtime-${target}")
    add_custom_command(TARGET "${target}" POST_BUILD
      COMMAND "${Python3_EXECUTABLE}" -B "${helper}"
        --sdk "${FOUNDATION_SDK_ROOT}" --manifest-sha256 "${manifest}"
        --executable "$<TARGET_FILE:${target}>" --target "${target}"
        --processor "${CMAKE_SYSTEM_PROCESSOR}"
      COMMENT "Auditing private SDK development runtime for ${target}" VERBATIM)
    set_property(TARGET "${target}" APPEND PROPERTY LINK_DEPENDS
      "${helper}" "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../tools/stage_runtime.py"
      "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../tools/verify_abi.py"
      "${CMAKE_CURRENT_FUNCTION_LIST_FILE}")
  endforeach()
endfunction()

# Call after target install rules and before installed runtime staging/auditing.
# Only destinations recorded by this install invocation are eligible; absent
# components, uninstalled test targets and preexisting unrelated files are ignored.
function(foundation_install_sdk_runtime)
  if(NOT FOUNDATION_SDK_ROOT OR NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    return()
  endif()
  _foundation_sdk_install_literal("${CMAKE_INSTALL_BINDIR}" "installation directory")
  _foundation_sdk_install_literal("${CMAKE_EXECUTABLE_SUFFIX}" "executable suffix")
  get_property(targets GLOBAL PROPERTY FOUNDATION_SDK_ALL_RUNTIME_TARGETS)
  set(preflight "set(foundation_sdk_installed_destinations)\n")
  set(rewrite "")
  foreach(target IN LISTS targets)
    if(IS_ABSOLUTE "${CMAKE_INSTALL_BINDIR}")
      set(destination "${CMAKE_INSTALL_BINDIR}/$<TARGET_FILE_NAME:${target}>")
    else()
      set(destination "\${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}/$<TARGET_FILE_NAME:${target}>")
    endif()
    string(APPEND preflight "
      set(destination \"${destination}\")
      list(FIND CMAKE_INSTALL_MANIFEST_FILES \"\${destination}\" installed_index)
      if(NOT installed_index EQUAL -1)
        list(FIND foundation_sdk_installed_destinations \"\${destination}\" duplicate_index)
        if(NOT duplicate_index EQUAL -1)
          message(FATAL_ERROR \"Ambiguous installed SDK executable destination: \${destination}\")
        endif()
        list(APPEND foundation_sdk_installed_destinations \"\${destination}\")
      endif()
    ")
    string(APPEND rewrite "
      set(destination \"${destination}\")
      list(FIND CMAKE_INSTALL_MANIFEST_FILES \"\${destination}\" installed_index)
      if(NOT installed_index EQUAL -1)
        if(IS_SYMLINK \"\$ENV{DESTDIR}\${destination}\")
          message(FATAL_ERROR \"Installed SDK executable must not be a symlink\")
        endif()
        file(RPATH_CHANGE FILE \"\$ENV{DESTDIR}\${destination}\"
          OLD_RPATH \"\$ORIGIN/.sdk-runtime/${target}\"
          NEW_RPATH \"$<TARGET_PROPERTY:${target},FOUNDATION_SDK_INSTALL_RPATH>\")
      endif()
    ")
  endforeach()
  install(CODE "${preflight}${rewrite}" ALL_COMPONENTS)
endfunction()
