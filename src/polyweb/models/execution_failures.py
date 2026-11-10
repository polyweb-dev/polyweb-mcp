"""Transport-neutral execution failures (TASK-000045).

The execution service, the execution authority, and every transport compose on
these classes. They carry a caller-safe ``detail`` only: no request content, no
credential material, and no internal file or SQL text. Transports project them
onto their own status codes and tool errors.
"""

from __future__ import annotations


class ExecutionError(Exception):
    """Execution failure before or around the provider call.

    ``detail`` is a caller-safe message without request data or secrets.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ExecutionStorageUnavailable(ExecutionError):
    """The service was composed without a repository or secret store."""


class ExecutionBindingMissing(ExecutionError):
    """No enabled usable binding exists for this project and operation."""


def missing_pool_detail(providers: tuple[str, ...] | list[str] | None = None) -> str:
    """Return the actionable refusal when no pool is assigned for a request.

    The text keeps the historical ``no ... provider is configured`` prefix so
    existing status assertions hold, then names pool creation/assignment for
    the selected provider(s). It never mentions timeouts: a missing pool
    fails before any provider call, while genuine timeouts surface through
    the 429 deadline path and 5xx provider errors.
    """

    names = sorted({provider for provider in (providers or ()) if provider})
    if names:
        joined = ", ".join(names)
        return (
            f"no required provider is configured for this project: {joined} "
            "has no assigned pool; create a pool for the selected provider "
            "and assign it to this project, then retry"
        )
    return (
        "no provider is configured for this project: the project has no "
        "assigned pool; create a pool for the selected provider and assign "
        "it to this project, then retry"
    )


class ExecutionNotPermitted(ExecutionBindingMissing):
    """The verified actor no longer holds live authority for this execution.

    Raised when the live re-authorization (account, user, membership and
    role, or API key revocation, expiry, project and scopes, plus an active
    project) fails after the boundary admitted the request. It subclasses
    :class:`ExecutionBindingMissing` because, like a missing binding, no
    provider is reachable; transports project it as a permission failure.
    """


class ExecutionAllFailed(ExecutionError):
    """Every provider leg of a fanout failed with a handled provider error."""


class ExecutionRequestInvalid(ExecutionError):
    """The request shape cannot be executed (transports map this to 4xx)."""


class ExecutionQueueSaturated(ExecutionError):
    """The bounded queue for a shared pool cannot admit this request now."""

    retriable = False

    def __init__(self, detail: str, *, retry_after_seconds: int = 1) -> None:
        super().__init__(detail)
        self.retry_after_seconds = max(1, retry_after_seconds)


class ExecutionQueueExpired(ExecutionError):
    """Queued work reached its wait bound before the authority could dispatch it."""

    retriable = True

    def __init__(self, detail: str, *, retry_after_seconds: int = 1) -> None:
        super().__init__(detail)
        self.retry_after_seconds = max(1, retry_after_seconds)


class ExecutionAuthorityUnavailable(ExecutionError):
    """No live, fenced execution authority may dispatch for this borrowed pool.

    Raised when another process holds the authority lease, when the authority
    is recovering from an earlier incarnation, or when the lease store fails.
    Execution fails closed: no provider call and no direct bypass.
    """

    retriable = True


__all__ = [
    "ExecutionAllFailed",
    "ExecutionAuthorityUnavailable",
    "ExecutionBindingMissing",
    "ExecutionError",
    "ExecutionNotPermitted",
    "ExecutionQueueExpired",
    "ExecutionQueueSaturated",
    "ExecutionRequestInvalid",
    "ExecutionStorageUnavailable",
    "missing_pool_detail",
]
