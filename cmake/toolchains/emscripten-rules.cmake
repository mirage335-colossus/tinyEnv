# CMake loads the supplier platform again while initializing each language.
# Reapply retained launchers after that load, before generating build rules.
# These wrappers keep the prepared cache immutable in direct CMake builds too.
set(CMAKE_C_COMPILER "${FOUNDATION_SDK_ROOT}/bin/emcc")
set(CMAKE_CXX_COMPILER "${FOUNDATION_SDK_ROOT}/bin/em++")
set(CMAKE_AR "${FOUNDATION_SDK_ROOT}/bin/emar")
set(CMAKE_RANLIB "${FOUNDATION_SDK_ROOT}/bin/emranlib")
set(CMAKE_C_COMPILER_AR "${CMAKE_AR}")
set(CMAKE_CXX_COMPILER_AR "${CMAKE_AR}")
set(CMAKE_C_COMPILER_RANLIB "${CMAKE_RANLIB}")
set(CMAKE_CXX_COMPILER_RANLIB "${CMAKE_RANLIB}")
