#!/bin/sh
# Backticks and guarded argument expansion support traditional Bourne sh too.
# shellcheck disable=SC2006
set -eu

# Usage: ./editor.sh [editor arguments, e.g. --project editor/self/project.json]
# Prefer the retained native SDK documented in COMPILE-editor. Without it,
# use the system toolchain in the build wrapper's default development tree.
script_path=$0
case $script_path in /*) ;; *) script_path=./$script_path ;; esac
script_dir=`dirname "$script_path"`
root=`CDPATH='' cd "$script_dir" && pwd`
cd "$root"
sdk="$root/build/agents/rust-package-qualification/sdk"
build_dir="$root/build/editor-fltk-dev"
if [ -f "$sdk/sdk.json" ]; then
    build_dir="$root/build/editor-fltk-sdk"
fi
editor="$build_dir/foundation-editor-fltk"

# Reuse an existing executable; rebuilding after source edits is explicit.
if [ ! -x "$editor" ]; then
    if [ -f "$sdk/sdk.json" ]; then
        ./build.sh editor build dev --backend fltk --sdk "$sdk" --build-dir "$build_dir"
    else
        ./build.sh editor build dev --backend fltk --build-dir "$build_dir"
    fi
fi

exec "$editor" ${1+"$@"}
