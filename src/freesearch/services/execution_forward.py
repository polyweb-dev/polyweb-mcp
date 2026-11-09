"""MCP-to-authority forwarding (TASK-000045).

A standalone MCP server must not run a second fair scheduler for a borrowed
pool. It forwards the original request to the API process that hosts the one
fenced execution authority, carrying the verified project credential it
received, the logical request's absolute deadline, and the current trace id.
The authority re-verifies the credential against live state and performs the
only provider dispatch.

The forwarder never exposes provider payloads or credentials in its errors: a
transport status becomes one safe category, and a queue or rate refusal stays
distinct from an authority outage.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import SecretStr

from freesearch.infrastructure.observability_asgi import (
    FORWARD_SIGNATURE_HEADER,
    FORWARD_TIMESTAMP_HEADER,
    PARENT_SPAN_HEADER,
    TRACE_HEADER,
    sign_forwarded_trace,
)
from freesearch.models.contracts import FetchRequest, FetchResponse, SearchRequest, SearchResponse

DEADLINE_HEADER = "x-freesearch-deadline-ms"

#: The only wire details forwarded to the tool surface. Anything else stays a
#: generic safe category so provider payloads or internal text never leak.
_SAFE_WIRE_DETAILS = (
    "the execution queue count bound is full",
    "the execution queue byte bound is full",
    "the execution queue wait bound expired before dispatch",
    "the execution request deadline expired before dispatch",
    "the execution request deadline expired before the provider call",
    "the execution request deadline expired during the provider call",
    "the execution admission count bound is full",
)


class ExecutionForwardError(RuntimeError):
    """One safe forwarding failure category, never carrying response content.

    ``category`` names the allowlisted refusal shape and
    ``retry_after_seconds`` preserves a wire Retry-After for the tool surface.
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = "execution_unavailable",
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retry_after_seconds = retry_after_seconds


class ExecutionForwarder:
    """Forward Search and Fetch calls to the API-hosted execution authority."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def search(
        self,
        request: SearchRequest,
        *,
        credential: SecretStr,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        deadline_ms: int | None = None,
    ) -> SearchResponse:
        body = await self._post(
            "/search",
            request.model_dump(mode="json", by_alias=True),
            credential=credential,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            deadline_ms=deadline_ms,
        )
        return SearchResponse.model_validate(body)

    async def fetch(
        self,
        request: FetchRequest,
        *,
        credential: SecretStr,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        deadline_ms: int | None = None,
    ) -> FetchResponse:
        body = await self._post(
            "/fetch",
            request.model_dump(mode="json", by_alias=True),
            credential=credential,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            deadline_ms=deadline_ms,
        )
        return FetchResponse.model_validate(body)

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        credential: SecretStr,
        trace_id: str | None,
        parent_span_id: str | None,
        deadline_ms: int | None,
    ) -> dict[str, Any]:
        headers, timeout = self._forward_request_headers(
            path,
            payload,
            credential=credential,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            deadline_ms=deadline_ms,
        )
        try:
            if timeout is None:
                response = await self._client.post(path, json=payload, headers=headers)
            else:
                response = await self._client.post(
                    path,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
        except httpx.HTTPError as error:
            raise ExecutionForwardError(
                "execution is temporarily unavailable", category="authority_unavailable"
            ) from error
        self._raise_wire_refusal(response)
        body = response.json()
        if not isinstance(body, dict):
            raise ExecutionForwardError(
                "execution returned an invalid response", category="invalid_response"
            )
        return body

    @staticmethod
    def _forward_request_headers(
        path: str,
        payload: dict[str, Any],
        *,
        credential: SecretStr,
        trace_id: str | None,
        parent_span_id: str | None,
        deadline_ms: int | None,
    ) -> tuple[dict[str, str], float | None]:
        """Build the signed headers and remaining per-request timeout."""

        secret = credential.get_secret_value()
        headers = {
            "Authorization": f"Bearer {secret}",
            "Accept": "application/json",
        }
        if trace_id and parent_span_id:
            timestamp = int(time.time())
            project_id = str(payload.get("project_id", ""))
            headers[TRACE_HEADER] = trace_id
            headers[PARENT_SPAN_HEADER] = parent_span_id
            headers[FORWARD_TIMESTAMP_HEADER] = str(timestamp)
            headers[FORWARD_SIGNATURE_HEADER] = sign_forwarded_trace(
                secret,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                project_id=project_id,
                timestamp=timestamp,
                method="POST",
                path=path,
            )
        timeout: float | None = None
        if deadline_ms is not None:
            headers[DEADLINE_HEADER] = str(deadline_ms)
            remaining = (deadline_ms - int(time.time() * 1000)) / 1000.0
            if remaining <= 0:
                raise ExecutionForwardError(
                    "the execution request deadline expired before forwarding",
                    category="queue_expired",
                )
            timeout = remaining
        return headers, timeout

    @staticmethod
    def _raise_wire_refusal(response: httpx.Response) -> None:
        """Raise the safe category for one non-success wire status."""

        if response.status_code == 401:
            raise ExecutionForwardError("not authenticated", category="authentication_required")
        if response.status_code == 403:
            raise ExecutionForwardError("execution is not permitted", category="not_permitted")
        if response.status_code == 402:
            raise ExecutionForwardError("provider spend is exhausted", category="spend_exhausted")
        if response.status_code == 429:
            retry_after = _retry_after_seconds(response)
            category, detail = _capacity_category(response)
            message = "execution capacity is rate limited or its queue is full"
            if detail is not None:
                message = f"{message}: {detail}"
            if retry_after is not None:
                message = f"{message}; retry after {retry_after} seconds"
            raise ExecutionForwardError(
                message,
                category=category,
                retry_after_seconds=retry_after,
            )
        if response.status_code >= 500:
            raise ExecutionForwardError(
                "execution is temporarily unavailable", category="authority_unavailable"
            )
        if response.status_code >= 400:
            raise ExecutionForwardError(
                "execution request was rejected", category="request_rejected"
            )

    async def aclose(self) -> None:
        """Close a client this forwarder created; injected clients stay owned."""

        if self._owns_client:
            await self._client.aclose()


def _retry_after_seconds(response: httpx.Response) -> int | None:
    """Return a positive wire Retry-After delay, or ``None`` when malformed."""

    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = int(raw.strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value >= 1 else None


def _capacity_category(response: httpx.Response) -> tuple[str, str | None]:
    """Map a capacity refusal to one allowlisted category and safe detail."""

    try:
        body = response.json()
    except ValueError:
        return ("rate_limited", None)
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str) and detail in _SAFE_WIRE_DETAILS:
        if "count bound" in detail or "admission count" in detail:
            return ("queue_saturated", detail)
        if "wait bound" in detail or "deadline expired" in detail:
            return ("queue_expired", detail)
        if "byte bound" in detail:
            return ("queue_saturated", detail)
        return ("rate_limited", detail)
    return ("rate_limited", None)


def deadline_from_timeout(timeout_seconds: float) -> int:
    """Return an absolute epoch-millisecond deadline at the configured timeout.

    A short configured timeout stays short: the forwarding deadline is the
    caller's whole budget, so it is never extended to an unrelated one-second
    floor.
    """

    return int(time.time() * 1000) + max(1, round(timeout_seconds * 1000))


__all__ = [
    "DEADLINE_HEADER",
    "TRACE_HEADER",
    "ExecutionForwardError",
    "ExecutionForwarder",
    "deadline_from_timeout",
]
