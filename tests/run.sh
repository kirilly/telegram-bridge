#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$ROOT/tests/test-contract.sh"
python3 "$ROOT/tests/check-infra-coverage-matrix.py"
