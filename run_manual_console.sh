#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
exec python3 manual_review_console.py --port 8765
