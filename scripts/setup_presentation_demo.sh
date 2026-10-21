#!/bin/bash
# Install machine-local dependencies and build the matching reviewer frontend.
set -euo pipefail
CODE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$CODE_ROOT"
for dependency in git uv node npm; do
  command -v "$dependency" >/dev/null || { echo "Install $dependency first (see docs/presentation-demo-handoff.md)." >&2; exit 1; }
done
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend run build
echo 'Setup complete. Run scripts/launch_presentation_demo.sh --scan-root "/path/to/Wilfred_Prest_Survey_Data"'
