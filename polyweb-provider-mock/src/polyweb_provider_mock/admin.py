"""The ``/_mock`` admin API: the CLI operations over HTTP, on the mock's own host.

Every route calls the same :class:`~polyweb_provider_mock.store.MockStore`
methods as ``polyweb-mock``. When ``POLYWEB_PROVIDER_MOCK_ADMIN_TOKEN`` is set,
every route except ``/_mock/health`` and the plugin pages needs the token:
``Authorization: Bearer <token>``, an ``admin_token`` form field, or the admin
cookie (see :mod:`polyweb_provider_mock.access`).
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from polyweb_provider_mock.access import AdminAccess
from polyweb_provider_mock.faults import FaultKind, FaultRule, FaultSpec
from polyweb_provider_mock.models import (
    Account,
    ApiKey,
    Fixture,
    KeylessSetting,
    LogEntry,
    PriceRule,
    PricingRule,
)
from polyweb_provider_mock.providers.base import ProviderPlugin
from polyweb_provider_mock.scenarios import apply_scenario, clear_scenarios, scenarios
from polyweb_provider_mock.store import MockStore, NotFoundError

__all__ = ["build_admin_app", "dotenv_lines"]


class SeedBody(BaseModel):
    reset: bool = False


class KeyBody(BaseModel):
    provider: str
    account_id: str | None = None
    label: str | None = None
    key: str | None = None
    scopes: list[str] = Field(default_factory=list)
    env_var: str | None = None
    credit_limit: Decimal | None = None


class KeyRefBody(BaseModel):
    provider: str
    key: str


class CreditsBody(BaseModel):
    provider: str
    amount: Decimal | None
    account_id: str | None = None
    used: Decimal | None = None


class PriceBody(BaseModel):
    provider: str
    operation: str
    credits_per_unit: Decimal
    usd_per_unit: Decimal | None = None
    unit: str = "request"
    rule: PricingRule = "per_unit"


class AttributesBody(BaseModel):
    provider: str
    attributes: dict[str, Any]
    account_id: str | None = None


class KeylessBody(BaseModel):
    provider: str
    enabled: bool | None = None
    per_day: int | None = None
    per_minute: int | None = None


class LatencyBody(BaseModel):
    provider: str
    ms: float = Field(ge=0)
    jitter_ms: float = Field(default=0.0, ge=0)
    operation: str = "*"


class FixtureBody(BaseModel):
    provider: str
    operation: str
    match_key: str
    body: Any
    status: int = 200


class FixtureFromLogBody(BaseModel):
    log_id: int
    match_key: str | None = None


def dotenv_lines(store: MockStore) -> str:
    """Return ``POLYWEB_<PROVIDER>_API_KEY=<mock key>`` lines for the seeded keys."""

    return "".join(f"{name}={value}\n" for name, value in store.export_keys())


def _guard(access: AdminAccess) -> Any:
    async def check(request: Request) -> None:
        if not await access.allowed(request):
            raise HTTPException(status_code=401, detail="admin token required")

    return Depends(check)


def _known(plugins: Mapping[str, ProviderPlugin], provider: str) -> ProviderPlugin:
    if provider not in plugins:
        raise HTTPException(status_code=404, detail=f"unknown provider {provider!r}")
    return plugins[provider]


def _state_routes(
    router: APIRouter, store: MockStore, plugins: Mapping[str, ProviderPlugin]
) -> None:
    """Register key, credit, pricing, and keyless routes."""

    @router.get("/keys")
    async def keys(provider: str | None = None) -> list[ApiKey]:
        return store.keys(provider)

    @router.post("/keys")
    async def create_key(body: KeyBody) -> ApiKey:
        plugin = _known(plugins, body.provider)
        return store.create_key(
            body.provider,
            plugin.key_format,
            account_id=body.account_id,
            label=body.label,
            key=body.key,
            scopes=body.scopes,
            env_var=body.env_var,
            credit_limit=body.credit_limit,
        )

    @router.post("/keys/revoke")
    async def revoke_key(body: KeyRefBody) -> ApiKey:
        return store.set_key_status(body.provider, body.key, "revoked")

    @router.post("/keys/restore")
    async def restore_key(body: KeyRefBody) -> ApiKey:
        return store.set_key_status(body.provider, body.key, "active")

    @router.get("/credits")
    async def credits(provider: str | None = None) -> list[Account]:
        return store.accounts(provider)

    @router.post("/credits/add")
    async def add_credits(body: CreditsBody) -> Account:
        if body.amount is None:
            raise HTTPException(status_code=400, detail="amount is required")
        return store.add_credits(body.provider, body.amount, body.account_id)

    @router.post("/credits/set")
    async def set_credits(body: CreditsBody) -> Account:
        return store.set_credits(body.provider, body.amount, body.account_id, used=body.used)

    @router.put("/accounts/attributes")
    async def set_attributes(body: AttributesBody) -> Account:
        _known(plugins, body.provider)
        return store.set_account_attributes(body.provider, body.attributes, body.account_id)

    @router.get("/pricing")
    async def pricing(provider: str | None = None) -> list[PriceRule]:
        return store.prices(provider)

    @router.put("/pricing")
    async def set_pricing(body: PriceBody) -> PriceRule:
        _known(plugins, body.provider)
        return store.set_price(PriceRule(**body.model_dump()))

    @router.get("/keyless")
    async def keyless() -> list[KeylessSetting]:
        return store.keyless_settings()

    @router.put("/keyless")
    async def set_keyless(body: KeylessBody) -> KeylessSetting:
        _known(plugins, body.provider)
        changes = body.model_dump(exclude_unset=True, exclude={"provider"})
        return store.set_keyless(body.provider, **changes)


def _fault_routes(
    router: APIRouter, store: MockStore, plugins: Mapping[str, ProviderPlugin]
) -> None:
    """Register fault, latency, and scenario routes."""

    @router.get("/faults")
    async def faults() -> list[FaultRule]:
        return store.faults()

    @router.post("/faults")
    async def add_fault(spec: FaultSpec) -> FaultRule:
        return store.add_fault(spec)

    @router.delete("/faults")
    async def clear_faults(
        id: int | None = None,
        provider: str | None = None,
        scenario: str | None = None,
        kind: FaultKind | None = None,
    ) -> dict[str, int]:
        removed = store.clear_faults(rule_id=id, provider=provider, scenario=scenario, kind=kind)
        return {"removed": removed}

    @router.put("/latency")
    async def latency(body: LatencyBody) -> FaultRule | None:
        return store.set_latency(body.provider, body.ms, body.jitter_ms, operation=body.operation)

    @router.get("/scenarios")
    async def list_scenarios() -> list[dict[str, Any]]:
        return [
            {"name": item.name, "description": item.description}
            for item in scenarios(plugins).values()
        ]

    @router.post("/scenarios/{name}")
    async def apply(name: str) -> list[FaultRule]:
        try:
            return apply_scenario(store, name, plugins)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from None

    @router.delete("/scenarios")
    async def clear_all() -> dict[str, int]:
        return {"removed": clear_scenarios(store, plugins)}

    @router.delete("/scenarios/{name}")
    async def clear(name: str) -> dict[str, int]:
        return {"removed": clear_scenarios(store, plugins, name)}


def _data_routes(
    router: APIRouter, store: MockStore, plugins: Mapping[str, ProviderPlugin]
) -> None:
    """Register provider listing, seed, reset, fixture, log, and key export routes."""

    @router.get("/providers")
    async def providers() -> list[dict[str, Any]]:
        return [
            {
                "name": plugin.name,
                "hosts": sorted(plugin.hosts),
                "operations": [
                    {
                        "name": op.name,
                        "method": op.method,
                        "path": op.path,
                        "billable": op.billable,
                        "hosts": sorted(op.hosts or plugin.hosts),
                    }
                    for op in plugin.operations()
                ],
            }
            for plugin in plugins.values()
        ]

    @router.post("/seed")
    async def seed(body: SeedBody) -> dict[str, int]:
        return store.seed(plugins.values(), reset=body.reset)

    @router.post("/reset")
    async def reset() -> dict[str, str]:
        store.reset()
        return {"status": "reset"}

    @router.get("/fixtures")
    async def fixtures(provider: str | None = None) -> list[Fixture]:
        return store.fixtures(provider)

    @router.post("/fixtures")
    async def save_fixture(body: FixtureBody) -> Fixture:
        _known(plugins, body.provider)
        return store.save_fixture(
            body.provider, body.operation, body.match_key, body.body, status=body.status
        )

    @router.post("/fixtures/from-log")
    async def save_from_log(body: FixtureFromLogBody) -> Fixture:
        return store.save_fixture_from_log(body.log_id, match_key=body.match_key)

    @router.delete("/fixtures/{fixture_id}")
    async def delete_fixture(fixture_id: int) -> dict[str, bool]:
        return {"deleted": store.delete_fixture(fixture_id)}

    @router.get("/log")
    async def log(
        provider: str | None = None, limit: Annotated[int, Query(ge=1, le=1000)] = 20
    ) -> list[LogEntry]:
        return store.log_tail(provider, limit)

    @router.get("/log/{log_id}")
    async def log_entry(log_id: int) -> LogEntry:
        entry = store.log_entry(log_id)
        if entry is None:
            raise NotFoundError(f"no logged request {log_id}")
        return entry

    @router.get("/export-keys", response_class=PlainTextResponse)
    async def export_keys() -> str:
        return dotenv_lines(store)


def build_admin_app(
    store: MockStore, plugins: Mapping[str, ProviderPlugin], *, admin_token: str | None = None
) -> FastAPI:
    """Return the admin app served on the mock's own host names."""

    app = FastAPI(
        title="Polyweb provider mock",
        docs_url="/_mock/docs",
        redoc_url=None,
        openapi_url="/_mock/openapi.json",
    )

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/_mock/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "providers": sorted(plugins), "seeded": store.is_seeded()}

    access = AdminAccess(admin_token)
    router = APIRouter(prefix="/_mock", dependencies=[_guard(access)])
    for register in (_state_routes, _fault_routes, _data_routes):
        register(router, store, plugins)
    pages = APIRouter(prefix="/_mock")
    for plugin in plugins.values():
        plugin.admin_routes(router, store, access)
        plugin.admin_pages(pages, store, access)
    app.include_router(pages)
    app.include_router(router)
    return app
