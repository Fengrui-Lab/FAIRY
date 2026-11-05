#!/bin/sh
set -eu
demo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$demo_dir/serve.py" "$@"
