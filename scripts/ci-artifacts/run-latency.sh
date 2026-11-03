#!/usr/bin/env bash
set -euo pipefail
{
  uv run freesearch-db upgrade
  uv run behave tests/bdd/features/routing_latency.feature
  uv run pytest tests/integration/latency/ -q
} 2>&1 | tee routing-latency-tests.log
