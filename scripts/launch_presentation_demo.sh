#!/bin/bash
# Every invocation starts with a new data checkout, local remote and scan cache.
set -euo pipefail
CODE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$CODE_ROOT"
exec uv run --locked python scripts/review_presentation_demo.py "$@"
