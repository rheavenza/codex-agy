#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

cd "$(dirname "$(readlink -f "$0")")"

exec uv run python server.py
