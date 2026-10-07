# Export consistent host tools even when the builder already has newer ones.
PACKAGES += host-cmake host-ninja host-pkgconf
# Avoid probing unrelated builder libraries for optional host Python modules.
HOST_PYTHON3_CONF_ENV += \
	py_cv_module__zstd=n/a \
	py_cv_module__dbm=n/a \
	py_cv_module__gdbm=n/a \
	py_cv_module_readline=n/a

# Keep the C++ toolkit static so its objects use the application's selected
# compiler runtime instead of introducing a second dynamic C++ runtime floor.
FLTK_CONF_OPTS += --disable-shared
