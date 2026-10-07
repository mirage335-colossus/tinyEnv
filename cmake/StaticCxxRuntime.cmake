include_guard(GLOBAL)

# Compiler identity alone does not identify its selected C++ standard library.
# Call once after selecting the compiler, flags and portable policy. Never cache
# a successful probe across reconfiguration with different -stdlib/toolchain flags.
function(foundation_require_static_gnu_runtime)
  if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR
      NOT CMAKE_CXX_COMPILER_ID MATCHES "^(GNU|Clang)$")
    message(FATAL_ERROR "Portable native builds require Linux with the GNU C++ runtime, or MSVC on Windows; declare and qualify another runtime policy before enabling it")
  endif()
  include(CheckCXXSourceCompiles)
  set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
  set(CMAKE_REQUIRED_QUIET TRUE)
  unset(foundation_selected_gnu_runtime CACHE)
  check_cxx_source_compiles("#include <cstddef>
#ifndef __GLIBCXX__
#error The selected standard library is not libstdc++
#endif
int main() { return 0; }" foundation_selected_gnu_runtime)
  set(selected "${foundation_selected_gnu_runtime}")
  unset(foundation_selected_gnu_runtime CACHE)
  if(NOT selected)
    message(FATAL_ERROR "Portable Linux builds require the selected libstdc++ headers and static GNU runtime; libc++ and other runtime policies are not qualified")
  endif()
endfunction()

function(foundation_link_static_gnu_runtime target visibility)
  target_link_options(${target} ${visibility} -static-libstdc++ -static-libgcc
    "LINKER:--exclude-libs,libstdc++.a:libgcc.a:libgcc_eh.a")
endfunction()
