#!/usr/bin/env bash
# Único .sh del repo, y no lleva lógica: la regla es un solo runtime (Python).
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m unittest discover -s tests -t . "$@"
