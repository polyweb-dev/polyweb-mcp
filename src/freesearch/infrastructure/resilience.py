"""Retry, rate-limit cooldown, and circuit breaking for provider operations.

Stage 2 resilience: a small async wrapper around operations that use an HTTPX
client created externally by :func:`freesearch.http.create_async_client`.
No provider, routing, or configuration logic lives here.
"""

import asyncio
import email.utils
import math
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from contextvars import ContextVar
from typing import Any, Literal, Protocol, TypeVar, cast

import httpx
from pydantic import AliasChoices, AliasPath, BaseModel
from pydantic.fields import FieldInfo

from freesearch.infrastructure.logging import redact_secrets
from freesearch.models.contracts import ProviderError

T = TypeVar("T")

# Single shared retryable HTTP status policy for the resilience runner and all
# provider adapters: 429 (rate limit) plus the retryable 5xx set.
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
# Backwards-compatible alias; prefer RETRYABLE_STATUS_CODES for new imports.
_RETRYABLE_STATUS_CODES = RETRYABLE_STATUS_CODES


class DispatchObserver(Protocol):
    """Per-send capacity observer installed around one adapter call.

    The runner invokes ``begin`` immediately before each actual HTTP operation
    and ``end`` when that operation settles. A retry inside the runner is
    therefore a separately charged dispatch, not a free resend.
    """

    async def begin(self) -> object: ...

    async def end(
        self,
        token: object,
        *,
        result: object | None = None,
        error: BaseException | None = None,
        retryable: bool = False,
    ) -> None: ...


_DISPATCH_OBSERVER: ContextVar[DispatchObserver | None] = ContextVar(
    "freesearch_dispatch_observer", default=None
)


def install_dispatch_observer(observer: DispatchObserver | None) -> object:
    """Install the per-send observer for the current task context."""

    return _DISPATCH_OBSERVER.set(observer)


def reset_dispatch_observer(token: object) -> None:
    """Restore the previous observer token."""

    _DISPATCH_OBSERVER.reset(token)  # type: ignore[arg-type]


# Credential-like key tokens, compared against keys with all non-alphanumeric
# characters removed and lowercased, so ``api_key``, ``x-api-key``, ``access
# key``, and ``bearer_token`` all match.
_SENSITIVE_KEY_TOKENS = frozenset(
    {
        "accesskey",
        "apikey",
        "authorization",
        "bearer",
        "credential",
        "password",
        "privatekey",
        "secret",
        "token",
    }
)

# Auth scheme words: after a credential-like field name, the value can name
# the scheme and carry the credential after it (``Authorization: Basic
# <blob>``), so the scheme and credential are redacted as one unit.
_AUTH_SCHEME_WORDS = frozenset({"basic", "bearer", "digest", "mac", "negotiate", "token"})

# ``Bearer <token>`` including an optional separator, redacted as a unit so a
# preceding ``Authorization:`` field cannot swallow the keyword first. Quoted
# tokens (``Bearer "token with spaces"``) redact as a whole value, quotes kept.
_QUOTED_VALUE_PATTERN = r"(?P<quote>[\"'])(?:\\.|(?!(?P=quote)).)*(?P=quote)?"
_QUOTED_STRING_RE = re.compile(_QUOTED_VALUE_PATTERN)
# Quoted string with optional leading whitespace, for values following a
# keyword with a gap (e.g. the token after ``Bearer``).
_QUOTED_AFTER_RE = re.compile(r"\s*" + _QUOTED_VALUE_PATTERN)
_BEARER_RE = re.compile(
    r"(?i)\bbearer(?P<sep>(?:\s*:\s*|\s+))"
    r"(?:(?P<quoted>" + _QUOTED_VALUE_PATTERN + r")|[^\s,;\"']+)"
)

# Field prefixes only (``name:`` / ``name=``). Values are extracted separately:
# a prefix+value single match lets a non-sensitive word (``refused:``) swallow
# an adjacent credential field as its value. Quotes are left to the value
# matchers so ``password="multi word secret"`` redacts as a whole. Keys may
# start with a digit or contain dots (``2fa_token``, ``api.key``).
_FIELD_PREFIX_RE = re.compile(r"(?i)\b\w[\w.-]*\s*[:=]\s*")
_VALUE_RE = re.compile(r"[^\s,;\"']+")
# The word immediately before a field prefix, for multi-word credential names
# ("access key:") that the prefix regex can only capture the last word of.
_WORD_BEFORE_RE = re.compile(r"([A-Za-z0-9_-]+)[ \t]*\Z")

# Quoted key followed by a quoted or bare value (``{"api_key": sk-1}``): the
# bare alternative catches malformed or partially serialized payloads.
_QUOTED_FIELD_RE = re.compile(
    r"(?P<prefix>(?P<key_quote>[\"'])(?P<key>[^\"']+)(?P=key_quote)\s*[:=]\s*)"
    r"(?:(?P<value_quote>[\"'])(?:\\.|(?!(?P=value_quote)).)*(?P=value_quote)"
    r"|(?P<bare_value>[^\s,;\"'\]}]+))"
)

__all__ = [
    "RETRYABLE_STATUS_CODES",
    "CircuitOpenError",
    "ProviderOperationError",
    "ResilientRunner",
]


def _is_sensitive_key(key: str) -> bool:
    """True when ``key`` names a credential-like field (``api_key``, ``token``...)."""
    normalized = "".join(ch for ch in key.lower() if ch.isalnum())
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


def _redact_text(value: str) -> str:
    """Redact secret-like fields, auth-scheme credentials (``Bearer``,
    ``Basic``...), and compound credential fields (``access_token=``,
    ``client_secret=``, ``access_key=``, ``credential=``) in text."""

    def redact_quoted_field(match: re.Match[str]) -> str:
        if not _is_sensitive_key(match.group("key")):
            return match.group(0)
        quote = match.group("value_quote")
        if quote is None:
            return f"{match.group('prefix')}[REDACTED]"
        return f"{match.group('prefix')}{quote}[REDACTED]{quote}"

    def redact_bearer(match: re.Match[str]) -> str:
        quote = match.group("quote")
        if quote is not None:
            return f"Bearer{match.group('sep')}{quote}[REDACTED]{quote}"
        return f"Bearer{match.group('sep')}[REDACTED]"

    value = _QUOTED_FIELD_RE.sub(redact_quoted_field, value)
    value = _BEARER_RE.sub(redact_bearer, value)
    redacted: list[str] = []
    end = 0
    for match in _FIELD_PREFIX_RE.finditer(value):
        if match.start() < end:
            continue  # inside an already-redacted value
        field = match.group(0).rstrip(":= \t\"'")
        if not _is_sensitive_key(field):
            # Multi-word names (``access key:``): the prefix regex captures
            # only the final word, so also test it joined with the word
            # immediately before it.
            before = _WORD_BEFORE_RE.search(value[: match.start()])
            if before is None or not _is_sensitive_key(before.group(1) + field):
                continue
        quoted = _QUOTED_STRING_RE.match(value, match.end())
        if quoted is not None:
            # ``password="multi word secret"`` — redact the whole quoted value,
            # keeping the quotes, so suffix words cannot leak.
            quote = quoted.group("quote")
            redacted.extend(
                (
                    redact_secrets(value[end : match.start()]),
                    f"{match.group(0)}{quote}[REDACTED]{quote}",
                )
            )
            end = quoted.end()
            continue
        value_match = _VALUE_RE.match(value, match.end())
        if value_match is None:
            continue
        if value_match.group(0).lower() in _AUTH_SCHEME_WORDS:
            # "Authorization: Basic <credential>" — the value names an auth
            # scheme, so redact the scheme and the credential after it as one
            # unit; otherwise the gap redaction below would treat the scheme
            # word itself as the field's value and leave the credential
            # behind it in place.
            scheme = value_match.group(0)
            quoted_tail = _QUOTED_AFTER_RE.match(value, value_match.end())
            if quoted_tail is not None:
                quote = quoted_tail.group("quote")
                redacted.extend(
                    (
                        redact_secrets(value[end : match.start()]),
                        f"{match.group(0)}{scheme} {quote}[REDACTED]{quote}",
                    )
                )
                end = quoted_tail.end()
                continue
            tail = _VALUE_RE.search(value, value_match.end())
            redacted.extend(
                (
                    redact_secrets(value[end : match.start()]),
                    f"{match.group(0)}{scheme} [REDACTED]",
                )
            )
            end = tail.end() if tail else value_match.end()
            continue
        redacted.extend((redact_secrets(value[end : match.start()]), f"{match.group(0)}[REDACTED]"))
        end = value_match.end()
    redacted.append(redact_secrets(value[end:]))
    return "".join(redacted)


def _alias_names(alias: str | AliasChoices | AliasPath | None) -> list[str]:
    if isinstance(alias, str):
        return [alias]
    if isinstance(alias, AliasPath):
        return [part for part in alias.path if isinstance(part, str)]
    if isinstance(alias, AliasChoices):
        return [name for choice in alias.choices for name in _alias_names(choice)]
    return []


def _model_field_is_sensitive(name: str, field: FieldInfo) -> bool:
    """True when a model field's name, alias, serialization alias, or string
    validation aliases name a credential-like value."""
    candidates = [name]
    candidates.extend(_alias_names(field.alias))
    candidates.extend(_alias_names(field.serialization_alias))
    candidates.extend(_alias_names(field.validation_alias))
    return any(_is_sensitive_key(candidate) for candidate in candidates)


def _sanitize_details(details: dict[str, Any]) -> dict[str, Any]:
    """Return ``details`` with credential-like keys masked and values redacted.

    Values are recursively normalized to Pydantic-JSON-safe types: mappings,
    tuples/sets, and Pydantic models become plain ``dict``/``list`` values,
    ``bytes`` are decoded and redacted, strings are redacted, and any other
    object is replaced with a placeholder without invoking its ``repr``.
    """

    def clean(value: Any) -> Any:
        if isinstance(value, BaseModel):
            # Explicitly use stable internal names even when the model enables
            # serialize_by_alias, then redact by all configured alias channels.
            dumped = value.model_dump(by_alias=False)
            for name, field in type(value).model_fields.items():
                # Redact the stored field when any alias (``alias``,
                # ``serialization_alias``, string validation aliases) names a
                # credential, so a deceptively named internal field cannot
                # leak its value through serialization.
                if _model_field_is_sensitive(name, field):
                    dumped[name] = "[REDACTED]"
            return clean(dumped)
        if isinstance(value, Mapping):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                if isinstance(key, str):
                    cleaned_key = _redact_text(key)
                    cleaned[cleaned_key] = "[REDACTED]" if _is_sensitive_key(key) else clean(item)
                elif key is None or isinstance(key, (bool, int, float)):
                    cleaned[str(key)] = clean(item)
                else:
                    # Never call repr/str on an arbitrary mapping key.
                    cleaned["[REDACTED]"] = "[REDACTED]"
            return cleaned
        if isinstance(value, (list, tuple, set, frozenset)):
            return [clean(item) for item in value]
        if isinstance(value, bytes):
            try:
                return _redact_text(value.decode("utf-8"))
            except UnicodeDecodeError:
                return "[REDACTED]"
        if isinstance(value, str):
            return _redact_text(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return "[REDACTED]"

    return cast(dict[str, Any], clean(details))


class ProviderOperationError(Exception):
    """Resilience-owned wrapper carrying a normalized :class:`ProviderError`.

    ``ProviderError`` is a Pydantic model rather than an ``Exception``, so
    provider adapters raise this wrapper to surface failures through the
    resilience runtime. The message and the stored error are redaction-safe
    for logs and serialization: the message, provider, and code are masked,
    and details have credential-like keys and values redacted.
    """

    def __init__(self, error: ProviderError) -> None:
        super().__init__(_redact_text(f"{error.provider}: {error.code}: {error.message}"))
        self.error = ProviderError(
            provider=_redact_text(error.provider),
            code=_redact_text(error.code),
            message=_redact_text(error.message),
            retryable=error.retryable,
            status_code=error.status_code,
            details=_sanitize_details(error.details),
        )


class CircuitOpenError(ProviderOperationError):
    """Raised when the provider's circuit is open; the operation is not attempted."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            ProviderError(
                provider=provider,
                code="circuit_open",
                message="circuit is open; operation not attempted",
                retryable=False,
            )
        )


class _Probe:
    """Tracks whether a run holds the single half-open circuit probe.

    ``generation`` is the breaker generation at admission; outcomes from a
    stale generation are ignored so a late finish cannot rewrite breaker state.
    """

    __slots__ = ("generation", "holds_probe")

    def __init__(self, holds_probe: bool, generation: int) -> None:
        self.holds_probe = holds_probe
        self.generation = generation


async def _await_uninterruptibly(make: Callable[[], Awaitable[None]]) -> None:
    """Await a lock-protected cleanup to completion even under cancellation.

    Cancellation can hit the lock acquisition and abandon the cleanup, so retry
    until it actually runs; cancellations arriving mid-cleanup are consumed
    while the caller's original exception keeps propagating.
    """

    while True:
        try:
            await make()
        except asyncio.CancelledError:
            continue
        return


class _CircuitBreaker:
    """Per-provider circuit breaker plus rate-limit cooldown, lock-protected."""

    def __init__(
        self,
        provider: str,
        *,
        threshold: int,
        cooldown: float,
        clock: Callable[[], float],
        sleeper: Callable[[float], Awaitable[None]],
    ) -> None:
        self._provider = provider
        self._threshold = threshold
        self._cooldown = cooldown
        self._clock = clock
        self._sleeper = sleeper
        self._lock = asyncio.Lock()
        self._state: Literal["closed", "open", "half_open"] = "closed"
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._rate_limited_until: float | None = None
        self._generation = 0

    async def begin(self) -> _Probe:
        """Return permission to run; fail fast while open, allow one half-open probe."""
        async with self._lock:
            now = self._clock()
            if self._state == "open":
                assert self._opened_at is not None
                if now < self._opened_at + self._cooldown:
                    raise CircuitOpenError(self._provider)
                self._state = "half_open"
                self._generation += 1
            if self._state == "half_open":
                if self._probe_in_flight:
                    raise CircuitOpenError(self._provider)
                self._probe_in_flight = True
                return _Probe(True, self._generation)
            return _Probe(False, self._generation)

    async def finish(self, probe: _Probe, *, success: bool, retryable: bool) -> None:
        """Record an outcome.

        A success or a definitive (non-retryable) answer closes the circuit;
        retryable failures count toward opening it, and a failed half-open
        probe re-opens it immediately. Outcomes admitted under an earlier
        breaker generation are stale (the circuit changed under them) and are
        dropped so a late success cannot close a newly opened breaker.
        """
        async with self._lock:
            if probe.holds_probe:
                self._probe_in_flight = False
            if probe.generation != self._generation:
                return
            if success or not retryable:
                self._close()
            elif self._state == "half_open":
                self._open(self._clock())
            elif self._state == "closed":
                self._failures += 1
                if self._failures >= self._threshold:
                    self._open(self._clock())

    async def release(self, probe: _Probe) -> None:
        """Clear a half-open probe claim without changing breaker state."""
        async with self._lock:
            if probe.holds_probe:
                self._probe_in_flight = False

    async def wait_for_rate_limit(self, already_slept: float | None = None) -> None:
        """Sleep until the provider rate-limit cooldown expires, if any.

        ``already_slept`` is the deadline a caller has just slept through
        itself (the retry backoff for the rate limit it recorded); it counts
        as waited out without another sleep. Re-checks after each sleep: a
        concurrent 429 can extend the recorded deadline while we wait, so a
        caller must not start before the latest one has elapsed. Sleeping for
        an unchanged deadline counts as having waited it out; only an extended
        deadline warrants another sleep.
        """
        slept_for: float | None = None
        while True:
            async with self._lock:
                until = self._rate_limited_until
                if until is None:
                    return
                remaining = until - self._clock()
                if remaining <= 0:
                    return
                if until in (slept_for, already_slept):
                    return  # deadline unchanged and already slept for it
            await self._sleeper(remaining)
            slept_for = until

    async def record_rate_limit(self, until: float) -> None:
        """Record the provider as rate-limited until ``until`` (clock time)."""
        async with self._lock:
            if self._rate_limited_until is None or until > self._rate_limited_until:
                self._rate_limited_until = until

    def _close(self) -> None:
        self._state = "closed"
        self._failures = 0
        self._opened_at = None
        self._generation += 1

    def _open(self, now: float) -> None:
        self._state = "open"
        self._failures = 0
        self._opened_at = now
        self._generation += 1


class ResilientRunner:
    """Retry and circuit-broken execution for operations using one HTTPX client.

    Construct with a client created by :func:`freesearch.http.create_async_client`,
    then wrap each provider operation::

        response = await runner.run(provider, lambda: client.get(url, params=params))

    Retries HTTP 429/500/502/503/504 responses, ``httpx.TransportError``
    failures, and retryable :class:`ProviderError` failures raised as
    :class:`ProviderOperationError`. Other exceptions propagate unchanged.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        circuit_failure_threshold: int = 5,
        circuit_cooldown: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        """Wrap ``client`` with retry and circuit-breaking policy.

        Policy values are constructor arguments so callers can tune them per
        operation without touching ``Settings``. ``clock``, ``wall_clock``,
        ``sleeper``, and ``random_source`` are injectable for deterministic
        tests: ``clock`` returns monotonic seconds for backoff and circuit
        timing, ``wall_clock`` returns wall-clock seconds for HTTP-date
        ``Retry-After`` parsing, the sleeper awaits a delay, and
        ``random_source`` returns a uniform value in ``[0, 1)`` used for
        backoff jitter. Retries are fixed to HTTP 429/500/502/503/504,
        transport errors, and retryable ``ProviderError`` failures.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if not math.isfinite(base_delay) or base_delay < 0:
            raise ValueError("base_delay must be non-negative")
        if not math.isfinite(max_delay) or max_delay < 0:
            raise ValueError("max_delay must be non-negative")
        if not math.isfinite(backoff_factor) or backoff_factor < 1:
            raise ValueError("backoff_factor must be at least 1")
        if circuit_failure_threshold < 1:
            raise ValueError("circuit_failure_threshold must be at least 1")
        if not math.isfinite(circuit_cooldown) or circuit_cooldown < 0:
            raise ValueError("circuit_cooldown must be non-negative")
        self.client = client
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._backoff_factor = backoff_factor
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_cooldown = circuit_cooldown
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleeper = sleeper
        self._random_source = random_source
        self._breakers: dict[str, _CircuitBreaker] = {}

    async def run(self, provider: str, operation: Callable[[], Awaitable[T]]) -> T:
        """Run ``operation`` with retries, Retry-After, and circuit protection.

        A 429 response records a provider-keyed rate-limit cooldown that later
        calls for the same provider wait out before starting, and its
        ``Retry-After`` header (when present) overrides the calculated backoff.
        A cancellation after admission counts as a failed probe only when this
        run held the half-open probe; a closed-state cancellation does not
        touch breaker state, so it cannot open a healthy circuit. The probe
        claim is always released — even under repeated cancellation — so a
        cancelled run cannot leave the circuit locked half-open.
        """
        breaker = self._breaker(provider)
        probe = await breaker.begin()
        try:
            return await self._attempt(provider, breaker, probe, operation)
        except asyncio.CancelledError:
            if probe.holds_probe:
                await _await_uninterruptibly(
                    lambda: breaker.finish(probe, success=False, retryable=True)
                )
            raise
        finally:
            await _await_uninterruptibly(lambda: breaker.release(probe))

    def _breaker(self, provider: str) -> _CircuitBreaker:
        breaker = self._breakers.get(provider)
        if breaker is None:
            breaker = _CircuitBreaker(
                provider,
                threshold=self._circuit_failure_threshold,
                cooldown=self._circuit_cooldown,
                clock=self._clock,
                sleeper=self._sleeper,
            )
            self._breakers[provider] = breaker
        return breaker

    async def _attempt(
        self,
        provider: str,
        breaker: _CircuitBreaker,
        probe: _Probe,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        last: ProviderOperationError | None = None
        # Rate-limit deadline covered by the previous retry sleep, credited to
        # the cooldown wait so the same deadline is not slept for twice.
        rate_limit_slept: float | None = None
        for attempt in range(self._max_attempts):
            status: int | None = None
            retry_after: float | None = None
            # Await the shared breaker cooldown before every attempt, not only
            # the first: a concurrent 429 extension observed during the local
            # backoff sleep must still be waited out.
            await breaker.wait_for_rate_limit(rate_limit_slept)
            rate_limit_slept = None
            observer = _DISPATCH_OBSERVER.get()
            token: object | None = None
            if observer is not None:
                token = await observer.begin()
            try:
                result = await operation()
            except ProviderOperationError as exc:
                if observer is not None and token is not None:
                    await observer.end(token, error=exc, retryable=exc.error.retryable)
                if not exc.error.retryable:
                    await breaker.finish(probe, success=False, retryable=False)
                    raise
                last = exc
                status = exc.error.status_code
                # Normalized vendor errors keep a parsed Retry-After delay in
                # their safe details; use this finite, nonnegative delay for
                # HTTP 429 instead of the calculated backoff. Header-less or
                # malformed delays keep the current backoff.
                retry_after = _finite_retry_after_details(exc.error.details)
            except httpx.TransportError as exc:
                if observer is not None and token is not None:
                    await observer.end(token, error=exc, retryable=True)
                last = self._transport_error(provider, exc)
            except Exception as exc:
                # Unexpected crashes are never retried; a held half-open probe
                # counts as failed so the circuit does not silently admit more.
                if observer is not None and token is not None:
                    await observer.end(token, error=exc, retryable=False)
                if probe.holds_probe:
                    await breaker.finish(probe, success=False, retryable=True)
                raise
            else:
                if (
                    isinstance(result, httpx.Response)
                    and result.status_code in RETRYABLE_STATUS_CODES
                ):
                    status = result.status_code
                    retry_after = self._retry_after_seconds(result)
                    last = ProviderOperationError(
                        ProviderError(
                            provider=provider,
                            code="http_error",
                            message=f"HTTP {result.status_code}",
                            retryable=True,
                            status_code=result.status_code,
                        )
                    )
                    if observer is not None and token is not None:
                        await observer.end(token, result=result, retryable=True)
                else:
                    if observer is not None and token is not None:
                        await observer.end(token, result=result)
                    await breaker.finish(probe, success=True, retryable=True)
                    return result

            delay = self._backoff_delay(attempt)
            if status == 429:
                delay = retry_after if retry_after is not None else delay
                cooldown_until = self._clock() + delay
                await breaker.record_rate_limit(cooldown_until)
                rate_limit_slept = cooldown_until
            if attempt + 1 >= self._max_attempts:
                await breaker.finish(probe, success=False, retryable=True)
                assert last is not None
                raise last
            await self._sleeper(delay)
        raise AssertionError("unreachable")

    def _backoff_delay(self, attempt: int) -> float:
        """Capped exponential backoff with full jitter for ``attempt`` failures."""
        with suppress(OverflowError):
            delay = min(self._max_delay, self._base_delay * self._backoff_factor**attempt)
            return delay * self._random_source()
        # A finite but huge backoff_factor overflows before min() caps it; the
        # max delay is the only safe value then. Zero base must stay zero.
        return 0.0 if self._base_delay == 0 else self._max_delay * self._random_source()

    def _retry_after_seconds(self, response: httpx.Response) -> float | None:
        """Parse ``Retry-After`` (integer seconds or HTTP-date) into seconds.

        Numeric values must be finite; non-finite or unparseable values yield
        ``None`` (the calculated backoff applies). HTTP-dates resolve against
        the wall clock, which is independent of the monotonic backoff/circuit
        clock.
        """
        value = response.headers.get("retry-after")
        if value is None:
            return None
        try:
            seconds = float(value)
        except (ValueError, OverflowError):
            pass
        else:
            if math.isfinite(seconds):
                return max(0.0, seconds)
        try:
            retry_at = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return max(0.0, retry_at.timestamp() - self._wall_clock())

    def _transport_error(self, provider: str, exc: httpx.TransportError) -> ProviderOperationError:
        return ProviderOperationError(
            ProviderError(
                provider=provider,
                code="transport_error",
                message=redact_secrets(str(exc)),
                retryable=True,
            )
        )


def _finite_retry_after_details(details: Any) -> float | None:
    """Return a finite, nonnegative ``Retry-After`` seconds value, else ``None``.

    The adapter preserves a parsed vendor ``Retry-After`` header in the safe
    error details as ``retry_after_seconds``. Only a real finite nonnegative
    number is honored; a missing, Boolean, or malformed value returns ``None``
    so the calculated backoff stays in effect.
    """

    if not isinstance(details, Mapping):
        return None
    value = details.get("retry_after_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _self_check() -> None:
    """Deterministic smoke check runnable as ``python -m freesearch.resilience``."""

    async def demo() -> None:
        now = 0.0
        sleeps: list[float] = []

        def clock() -> float:
            return now

        async def sleeper(delay: float) -> None:
            sleeps.append(delay)

        async with httpx.AsyncClient() as client:
            attempts = 0

            async def flaky() -> httpx.Response:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    return httpx.Response(429, headers={"Retry-After": "7"})
                return httpx.Response(200)

            runner = ResilientRunner(
                client,
                max_attempts=2,
                base_delay=2.0,
                clock=clock,
                sleeper=sleeper,
                random_source=lambda: 1.0,
            )
            assert (await runner.run("flaky", flaky)).status_code == 200
            assert attempts == 2
            assert sleeps == [7.0]  # Retry-After overrides the calculated backoff

            # HTTP-date Retry-After resolves against the wall clock, and
            # non-finite values are rejected instead of producing an
            # infinite/absurd cooldown.
            wall_now = 1_700_000_000.0
            delays: list[float] = []

            async def wall_sleeper(delay: float) -> None:
                delays.append(delay)

            def wall_clock() -> float:
                return wall_now

            date_runner = ResilientRunner(
                client,
                max_attempts=2,
                base_delay=2.0,
                clock=clock,
                wall_clock=wall_clock,
                sleeper=wall_sleeper,
                random_source=lambda: 1.0,
            )
            attempts = 0

            async def dated() -> httpx.Response:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    return httpx.Response(
                        429, headers={"Retry-After": "Thu, 01 Jan 2027 00:00:00 GMT"}
                    )
                return httpx.Response(200)

            retry_at = email.utils.parsedate_to_datetime("Thu, 01 Jan 2027 00:00:00 GMT")
            assert (await date_runner.run("dated", dated)).status_code == 200
            # wall clock, not monotonic
            assert delays == [max(0.0, retry_at.timestamp() - wall_now)]
            delays.clear()
            attempts = 0

            async def infinite() -> httpx.Response:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    return httpx.Response(429, headers={"Retry-After": "Infinity"})
                return httpx.Response(200)

            assert (await date_runner.run("infinite", infinite)).status_code == 200
            assert attempts == 2
            assert delays == [2.0]  # non-finite Retry-After falls back to backoff

            calls = 0

            async def bad_request() -> httpx.Response:
                nonlocal calls
                calls += 1
                return httpx.Response(400)

            assert (await runner.run("other", bad_request)).status_code == 400
            assert calls == 1  # non-retryable 4xx is not retried

            attempts = 0

            async def failing() -> httpx.Response:
                nonlocal attempts
                attempts += 1
                return httpx.Response(503)

            breaker_runner = ResilientRunner(
                client,
                max_attempts=1,
                circuit_failure_threshold=2,
                circuit_cooldown=5.0,
                clock=clock,
                sleeper=sleeper,
                random_source=lambda: 1.0,
            )
            for _ in range(2):
                with suppress(ProviderOperationError):
                    await breaker_runner.run("breaker", failing)
            assert attempts == 2
            fail_fast: Exception | None = None
            try:
                await breaker_runner.run("breaker", failing)
            except ProviderOperationError as exc:
                fail_fast = exc
            assert isinstance(fail_fast, CircuitOpenError)
            assert attempts == 2  # fail-fast does not touch the provider
            now = 5.0  # circuit cooldown elapsed -> one half-open probe

            async def ok() -> httpx.Response:
                return httpx.Response(200)

            assert (await breaker_runner.run("breaker", ok)).status_code == 200
            assert (await breaker_runner.run("breaker", ok)).status_code == 200

    asyncio.run(demo())


if __name__ == "__main__":
    _self_check()
