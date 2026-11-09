"""Typed failures of the provider control plane (bindings, pools, OAuth).

Transports map them once (see ``routers/control_errors.py``): not found is
HTTP 404, conflicts 409 and invalid requests 422 with a stable ``code``,
storage trouble 503 and an unreachable vendor 502. Messages never carry
secret material.
"""

from __future__ import annotations


class ControlPlaneError(RuntimeError):
    """Base class of typed control-plane failures."""


class ResourceNotFound(ControlPlaneError):
    """The resource is unknown or not visible to this caller (non-revealing)."""


class ResourceConflict(ControlPlaneError):
    """The request conflicts with durable state; ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ResourceInvalid(ControlPlaneError):
    """The request is semantically invalid; ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ControlStorageUnavailable(ControlPlaneError):
    """The store could not be read or could not serialize a write."""


class UpstreamUnavailable(ControlPlaneError):
    """The vendor endpoint failed or answered with an unusable response."""


__all__ = [
    "ControlPlaneError",
    "ControlStorageUnavailable",
    "ResourceConflict",
    "ResourceInvalid",
    "ResourceNotFound",
    "UpstreamUnavailable",
]
