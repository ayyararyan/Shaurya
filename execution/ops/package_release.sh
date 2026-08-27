#!/bin/sh
set -eu
case "$0" in */*) script_parent=${0%/*} ;; *) script_parent=. ;; esac
script_dir=$(CDPATH= cd -- "$script_parent" && pwd -P)
python_bin=$("$script_dir/libexec/select-python") || exit 70
exec "$python_bin" -I -B "$script_dir/libexec/portable_ops.py" --internal-package "$@"
