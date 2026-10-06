"""Thin HTTP handlers for the provider limit catalog, grants, and history.

Every handler reads its service from ``app.state.limits`` and returns the
service's contract. Status mapping is deliberate: 404 for an unknown provider or
rail, 422 for an invalid mode, operation, period, or link, 409 for a stale
version precondition, and 503 when no repository can serve a write. No handler
runs vendor I/O or raw SQL.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, cast
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from freesearch.configuration.provider_limits import PROVIDER_IDS
from freesearch.models.provider_limits import (
    MAX_HISTORY_PAGE_SIZE,
    AuthMode,
    CRDGrantPayload,
    LimitHistoryPage,
    LimitHistoryQuery,
    LimitOperation,
    LimitRecordNotFound,
    LimitRecordUpdate,
    LimitStoreUnavailable,
    LimitVersionConflict,
    ProviderLimitsResponse,
    SyncResult,
)
from freesearch.services.provider_limits import ProviderLimitsService

_CREDENTIAL_MARKER = "@"
_SAFE_SCHEME = "https://"


def register_limit_routes(app: FastAPI) -> None:
    """Register the limit endpoints on ``app``."""

    @app.get("/api/v1/providers/{provider_id}/limits", response_model=ProviderLimitsResponse)
    async def get_limits(provider_id: str, request: Request) -> ProviderLimitsResponse:
        """Return both auth modes, their views, tiers, and rate progress."""

        service = _service(request)
        return await _guard(provider_id, lambda: service.provider_view(provider_id))

    @app.patch(
        "/api/v1/providers/{provider_id}/limits/{auth_mode}/{operation}",
        response_model=ProviderLimitsResponse,
    )
    async def patch_limits(
        provider_id: str,
        auth_mode: str,
        operation: str,
        request: Request,
        body: Annotated[dict[str, object], Body()],
    ) -> ProviderLimitsResponse:
        """Apply a partial catalog update; omitted fields keep their value."""

        service = _service(request)
        change = _record_update(provider_id, auth_mode, operation, body)
        return await _guard(provider_id, lambda: service.update_record(change))

    @app.put(
        "/api/v1/providers/{provider_id}/crd-grants/{auth_mode}",
        response_model=ProviderLimitsResponse,
    )
    async def put_crd_grants(
        provider_id: str,
        auth_mode: str,
        payload: CRDGrantPayload,
        request: Request,
    ) -> ProviderLimitsResponse:
        """Store the operator credit-unit grant for one period and auth mode."""

        service = _service(request)
        mode = _auth_mode(auth_mode)
        if provider_id == "brave" and payload.fetch_crd > 0:
            raise HTTPException(status_code=422, detail="brave has no fetch rail")
        if payload.period_end <= payload.period_start:
            raise HTTPException(status_code=422, detail="period_end must be after period_start")
        return await _guard(provider_id, lambda: service.save_grant(provider_id, payload, mode))

    @app.get("/api/v1/providers/{provider_id}/limits/history", response_model=LimitHistoryPage)
    async def get_limit_history(
        provider_id: str,
        request: Request,
        auth_mode: str | None = None,
        limit: int = Query(default=50),
        cursor: str | None = None,
    ) -> LimitHistoryPage:
        """Return one page of a provider's audit history."""

        service = _service(request)
        query = LimitHistoryQuery(
            provider=provider_id,
            auth_mode=_auth_mode(auth_mode) if auth_mode is not None else None,
            limit=_history_limit(limit),
            cursor=cursor,
        )
        return await _guard(provider_id, lambda: service.history(query))

    @app.post("/api/v1/providers/{provider_id}/limits/sync", response_model=SyncResult)
    async def sync_limits(provider_id: str, request: Request) -> SyncResult:
        """Run one bounded provider sync under the mandatory lease and cadence."""

        _require_provider(provider_id)
        sync = getattr(request.app.state, "limits_sync", None)
        if sync is None:
            raise HTTPException(status_code=503, detail="no limit sync service is available")
        return await _guard(provider_id, lambda: sync.sync_provider(provider_id, datetime.now(UTC)))


def limit_denial_response(error: object) -> JSONResponse:
    """Build the REST response for one local admission denial."""

    provider_error = getattr(error, "error", None)
    status = int(getattr(provider_error, "status_code", None) or 402)
    retry_after = getattr(error, "retry_after_seconds", None)
    headers = (
        {"Retry-After": str(retry_after)} if retry_after is not None and status == 429 else None
    )
    detail = provider_error.model_dump(mode="json") if provider_error is not None else {}
    return JSONResponse(status_code=status, content={"detail": detail}, headers=headers)


def _service(request: Request) -> ProviderLimitsService:
    service = getattr(request.app.state, "limits", None)
    if service is None:
        raise HTTPException(status_code=503, detail="no limit store is available")
    return cast(ProviderLimitsService, service)


async def _guard[ResultT](provider_id: str, action: Callable[[], Awaitable[ResultT]]) -> ResultT:
    """Map service exceptions onto the documented HTTP status codes."""

    _require_provider(provider_id)
    try:
        return await action()
    except LimitRecordNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except LimitVersionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except LimitStoreUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _require_provider(provider_id: str) -> None:
    if provider_id not in PROVIDER_IDS:
        raise HTTPException(status_code=404, detail=f"unknown provider {provider_id!r}")


def _record_update(
    provider_id: str, auth_mode: str, operation: str, body: dict[str, object]
) -> LimitRecordUpdate:
    """Validate one partial catalog update before it reaches the service."""

    mode = _auth_mode(auth_mode)
    selected = _operation(operation)
    payload = dict(body)
    payload.update({"provider": provider_id, "auth_mode": mode.value, "operation": selected.value})
    _validate_usage_url(payload.get("usage_url"))
    if "version" not in payload:
        raise HTTPException(status_code=422, detail="version is required")
    if provider_id == "brave" and selected is LimitOperation.FETCH and body.get("supported"):
        raise HTTPException(status_code=422, detail="brave has no fetch rail")
    try:
        return LimitRecordUpdate.model_validate(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _validate_usage_url(value: object) -> None:
    """Allow only a safe HTTPS usage link without embedded credentials.

    The authority is parsed, not pattern-matched, so a user name or password in
    the host part is rejected as well as a trailing credential marker.
    """

    if value is None:
        return
    if not isinstance(value, str) or not value.startswith(_SAFE_SCHEME):
        raise HTTPException(status_code=422, detail="usage_url must be an https link")
    parts = urlsplit(value)
    if parts.username or parts.password or _CREDENTIAL_MARKER in parts.netloc:
        raise HTTPException(status_code=422, detail="usage_url must not carry credentials")
    if not parts.hostname:
        raise HTTPException(status_code=422, detail="usage_url must name a host")


def _auth_mode(value: str) -> AuthMode:
    try:
        return AuthMode(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"invalid auth mode {value!r}") from error


def _operation(value: str) -> LimitOperation:
    try:
        return LimitOperation(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"invalid limit operation {value!r}") from error


def _history_limit(value: int) -> int:
    if value < 1:
        raise HTTPException(status_code=422, detail="limit must be at least 1")
    return min(value, MAX_HISTORY_PAGE_SIZE)
