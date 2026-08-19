# Stage 2: Resilience Handoff

## Scope

Implement only the Stage 2 resilience worktree described in
[`WORKPLAN.md`](WORKPLAN.md): shared HTTPX timeout, retryable-error, backoff,
rate-limit, and circuit-breaker behavior.

Do not implement providers, routing, SQLite repositories, MCP transport, or
provider configuration. Do not edit `pyproject.toml` or `uv.lock`.

Existing shared components to reuse:

- `src/freesearch/http.py`: the only HTTPX client factory.
- `src/freesearch/contracts.py`: `ProviderError`, `ProviderHealth`, and
  `HealthStatus`.
- `src/freesearch/logging.py`: `redact_secrets` for log-safe errors.
- `tests/conftest.py`: async test conventions and `FakeAdapter`.

## Developer Agent

Own production code only. Do not create or edit test files.

1. Add `src/freesearch/resilience.py` with a small reusable async wrapper for
   provider HTTP operations.
2. Accept an HTTPX client created by `create_async_client`; do not add another
   HTTP client factory.
3. Retry HTTP 429, 500, 502, 503, and 504; HTTPX connection and timeout
   failures; and explicitly retryable normalized provider errors. Do not retry
   other 4xx responses.
4. Use a capped exponential backoff with jitter. Allow clock, sleep, and random
   behavior to be injected so tests do not wait or depend on real time.
5. Honor `Retry-After` for HTTP 429 responses. Record a per-provider cooldown
   so concurrent operations do not immediately retry the same rate-limited
   provider.
6. Implement a per-provider circuit breaker:
   - Start closed.
   - Open after the configured retryable-failure threshold.
   - Fail fast while open.
   - After the cooldown, allow one half-open recovery probe.
   - Close on a successful probe; re-open on a failed probe.
7. `ProviderError` is a Pydantic model rather than an exception. Add the
   smallest resilience-owned exception wrapper needed to carry a normalized
   `ProviderError`; make its message safe through `redact_secrets`.
8. Keep policy defaults as constructor arguments. Do not add resilience fields
   to `Settings`; safe HTTP tuning belongs to the configuration worktree.

## Tester Agent

Own `tests/test_resilience.py` only. Do not edit production files.

1. Test retry classification for retryable status codes, non-retryable 4xx,
   HTTPX connection/time-out failures, and normalized retryable errors.
2. Test attempts, capped exponential delays, deterministic jitter, and
   `Retry-After` taking precedence over calculated backoff.
3. Test that a 429 causes another operation for the same provider to respect
   the stored cooldown.
4. Test circuit-breaker transitions: closed to open at the threshold, fail-fast
   while open, one half-open probe after cooldown, close on recovery, and
   re-open after a failed probe.
5. Use fake async operations plus fake clock, sleeper, and random source. Do
   not make network calls or add test dependencies.

## Quality Criteria

Both agents must meet all of the following:

- Keep the change limited to the resilience worktree and reuse existing shared
  contracts and HTTPX setup.
- Add no dependencies and make no changes to `pyproject.toml` or `uv.lock`.
- Do not import vendor SDKs or provider-specific code.
- Preserve async behavior without blocking calls or real sleeps in tests.
- Never expose secret values in errors or logs.
- Keep APIs small, typed, and documented where behavior is not obvious.
- Avoid speculative abstractions and compatibility layers.
- Run and pass `uv run ruff check .`, `uv run mypy src`, and `uv run pytest`.
