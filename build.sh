#!/bin/sh
# Backticks and guarded argument expansion support traditional Bourne sh too.
# shellcheck disable=SC2006
set -eu
script_path=$0
case $script_path in /*) ;; *) script_path=./$script_path ;; esac
script_dir=`dirname "$script_path"`
root=`CDPATH='' cd "$script_dir" && pwd`
exec "${PYTHON:-python3}" "$root/tools/build.py" ${1+"$@"}
