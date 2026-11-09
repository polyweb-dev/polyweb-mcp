#!/usr/bin/env bash
# Preserve command failures and raw logs. Convert CR progress for Woodpecker.
set -euo pipefail
log_file=$1
shift
"$@" 2>&1 | tee "$log_file" | stdbuf -oL tr '\r' '\n'
