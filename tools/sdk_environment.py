"""One host-environment boundary for prepared SDK consumers and producers."""
import os

# These affect compiler selection, implicit headers/libraries, compiler subprocess
# lookup, package discovery or the loader running retained host tools.
HOST_OVERRIDES = (
    'CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'CPATH', 'C_INCLUDE_PATH',
    'CPLUS_INCLUDE_PATH', 'OBJC_INCLUDE_PATH', 'LIBRARY_PATH', 'PKG_CONFIG_PATH',
    'GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'LD_AUDIT',
)


def require_clean(environment=None):
    environment = os.environ if environment is None else environment
    for name in HOST_OVERRIDES:
        if environment.get(name):
            raise ValueError('unset host search override for SDK builds: ' + name)


def sanitized(environment=None):
    result = dict(os.environ if environment is None else environment)
    for name in HOST_OVERRIDES:
        result.pop(name, None)
    return result
