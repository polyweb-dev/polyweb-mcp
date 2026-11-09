"""Constrained string values stored by the settled alpha schema (TASK-000040).

Pure data: every member mirrors one database check constraint, so a value the
repositories accept is always a value the schema accepts.
"""

from enum import StrEnum


class UpstreamScope(StrEnum):
    """Boundary an upstream quota pool is enforced on by the provider."""

    ACCOUNT = "account"
    CREDENTIAL = "credential"
    IP = "ip"
    INSTALLATION = "installation"


class PoolStatus(StrEnum):
    """Lifecycle state of an upstream quota pool."""

    ACTIVE = "active"
    DISABLED = "disabled"


class OAuthGrantStatus(StrEnum):
    """Connection state of one per-credential OAuth grant."""

    PENDING = "pending"
    CONNECTED = "connected"
    REFRESH_FAILED = "refresh_failed"
    DISCONNECTED = "disconnected"


class AuditCategory(StrEnum):
    """System audit stream: administrative audit or security events."""

    AUDIT = "audit"
    SECURITY = "security"


class AuditActorType(StrEnum):
    """Principal class recorded on audit rows."""

    HUMAN = "human"
    PROJECT_API_KEY = "project_api_key"
    SYSTEM = "system"
    ANONYMOUS = "anonymous"


class AuditOutcome(StrEnum):
    """Result of one audited action."""

    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


class RetentionDataClass(StrEnum):
    """Project data class one retention run deletes from."""

    TRACES = "traces"
    USAGE = "usage"
    AUDIT = "audit"


class RetentionRunStatus(StrEnum):
    """Lifecycle state of one retention run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AuthorityState(StrEnum):
    """State of one execution-authority lease."""

    VACANT = "vacant"
    ACTIVE = "active"
    RECOVERING = "recovering"


class DispatchState(StrEnum):
    """Recovery state of one dispatched provider attempt."""

    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


__all__ = [
    "AuditActorType",
    "AuditCategory",
    "AuditOutcome",
    "AuthorityState",
    "DispatchState",
    "OAuthGrantStatus",
    "PoolStatus",
    "RetentionDataClass",
    "RetentionRunStatus",
    "UpstreamScope",
]
