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
from uuid import UUID

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from freesearch.configuration.provider_limits import PROVIDER_IDS
from freesearch.models.projects import PermissionAction
from freesearch.models.provider_limits import (
    MAX_HISTORY_PAGE_SIZE,
    AuthMode,
    LimitHistoryPage,
    LimitHistoryQuery,
    LimitOperation,
    LimitRecordNotFound,
    LimitRecordUpdate,
    LimitStoreUnavailable,
    LimitVersionConflict,
    ProviderLimitsResponse,
    SyncResult,
    VaultKeyUsage,
)
from freesearch.models.quota_api import (
    USDBudgetPayload,
    USDHistoryPage,
    USDProviderLimits,
    USDVaultKeyUsage,
)
from freesearch.models.users import UserPrincipal
from freesearch.routers.auth import current_principal, require_admin, require_control_reader
from freesearch.routers.control_errors import control_repository
from freesearch.services.authorization import ScopedAuthorizationService, system_query
from freesearch.services.execution import ExecutionService
from freesearch.services.limits_sync import add_vault_key_auth_status
from freesearch.services.provider_limits import ProviderLimitsService

#: Role gates follow the control-plane matrix: Admin guards every mutation and
#: the control reader guards the sanitized reads. Both answer 401 before 403,
#: and both run before any persistence write or vendor I/O.
_AdminPrincipal = Annotated[UserPrincipal, Depends(require_admin)]
_ReaderPrincipal = Annotated[UserPrincipal, Depends(require_control_reader)]
_Principal = Annotated[UserPrincipal, Depends(current_principal)]

_CREDENTIAL_MARKER = "@"
_SAFE_SCHEME = "https://"


def register_limit_routes(app: FastAPI) -> None:
    """Register the limit endpoints on ``app``."""

    @app.get("/api/v1/providers/{provider_id}/limits", response_model=USDProviderLimits)
    async def get_limits(
        _principal: _ReaderPrincipal, provider_id: str, request: Request
    ) -> ProviderLimitsResponse:
        """Return both auth modes, their views, tiers, and rate progress."""

        service = _service(request)
        return await _guard(provider_id, lambda: service.provider_view(provider_id))

    @app.patch(
        "/api/v1/providers/{provider_id}/limits/{auth_mode}/{operation}",
        response_model=USDProviderLimits,
    )
    async def patch_limits(
        _principal: _AdminPrincipal,
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
        "/api/v1/providers/{provider_id}/budgets/{auth_mode}",
        response_model=USDProviderLimits,
    )
    async def put_usd_budget(
        _principal: _AdminPrincipal,
        provider_id: str,
        auth_mode: str,
        payload: USDBudgetPayload,
        request: Request,
    ) -> ProviderLimitsResponse:
        """Store the operator USD budget for one period and auth mode."""

        service = _service(request)
        mode = _auth_mode(auth_mode)
        if provider_id == "brave" and payload.fetch_usd > 0:
            raise HTTPException(status_code=422, detail="brave has no fetch rail")
        if payload.period_end <= payload.period_start:
            raise HTTPException(status_code=422, detail="period_end must be after period_start")
        return await _guard(
            provider_id, lambda: service.save_grant(provider_id, payload.to_ledger(), mode)
        )

    @app.get("/api/v1/providers/{provider_id}/limits/history", response_model=USDHistoryPage)
    async def get_limit_history(
        _principal: _ReaderPrincipal,
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
    async def sync_limits(
        _principal: _AdminPrincipal, provider_id: str, request: Request
    ) -> SyncResult:
        """Run one bounded provider sync under the mandatory lease and cadence."""

        _require_provider(provider_id)
        sync = getattr(request.app.state, "limits_sync", None)
        if sync is None:
            raise HTTPException(status_code=503, detail="no limit sync service is available")
        return await _guard(provider_id, lambda: sync.sync_provider(provider_id, datetime.now(UTC)))

    @app.get("/api/v1/providers/{provider_id}/limits/keys", response_model=list[USDVaultKeyUsage])
    async def get_key_usage(
        _principal: _AdminPrincipal, provider_id: str, request: Request
    ) -> list[VaultKeyUsage]:
        """Return only quota observations and labels, never vault credentials."""

        _require_provider(provider_id)
        keys = await _execution(request).vault_key_usage(provider_id)
        return await add_vault_key_auth_status(control_repository(request), keys)

    @app.post(
        "/api/v1/providers/{provider_id}/limits/keys/{key_id}/sync", response_model=SyncResult
    )
    async def sync_key_usage(
        actor: _Principal, provider_id: str, key_id: UUID, request: Request
    ) -> SyncResult:
        """Poll one key only for its owner or a system administrator."""

        _require_provider(provider_id)
        execution = _execution(request)
        owner = await execution.vault_key_usage_owner(provider_id, key_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="key not found")
        if owner != actor.id:
            authorization = ScopedAuthorizationService(control_repository(request))
            decision = await authorization.authorize(
                system_query(actor, PermissionAction.SYSTEM_SETTINGS_WRITE)
            )
            if not decision.allowed:
                raise HTTPException(status_code=404, detail="key not found")
        return await execution.sync_vault_key_limits(provider_id, key_id, datetime.now(UTC))


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


def _execution(request: Request) -> ExecutionService:
    execution = getattr(request.app.state, "execution", None)
    if execution is None:
        raise HTTPException(status_code=503, detail="no execution service is available")
    return cast(ExecutionService, execution)


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
    profile = payload.get("conversion_profile")
    if isinstance(profile, dict) and "reference_usd_per_crd" in profile:
        raise HTTPException(status_code=422, detail="Prices use USD per native unit")
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
