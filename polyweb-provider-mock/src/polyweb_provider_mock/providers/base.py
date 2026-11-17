"""The provider plugin interface.

One module per provider lives in ``polyweb_provider_mock/providers/`` and
exports ``PLUGIN``, an instance of a :class:`ProviderPlugin` subclass. The
package discovers every module, so a new provider needs no central edit.

A plugin declares:

- ``name``, ``hosts`` (the real API hosts it answers), and ``key_format``.
- :meth:`ProviderPlugin.operations`: the real method and path of every
  endpoint, its operation name, whether it is billed, whether it accepts the
  keyless rail, which key scopes it needs, the hosts it is served on (all
  plugin hosts by default), and whether the request log may keep its bodies.
  Each operation has an async handler that receives an
  :class:`OperationContext` and returns a :class:`MockResponse` in the
  provider's success format.
- :meth:`ProviderPlugin.credentials`: how a request presents its key
  (bearer, header, or query) and whether it asks for keyless mode. It may
  read the store, for example to map a token to a key.
- :meth:`ProviderPlugin.default_seed` and :meth:`ProviderPlugin.default_pricing`.
- :meth:`ProviderPlugin.error`: the provider's real error status, headers,
  and body for every :class:`ErrorKind`. The :class:`ErrorContext` carries
  the store, the account, the request, and the presented key when known.
- Optional: :meth:`ProviderPlugin.response_headers` (including the real
  ``Server`` header; the mock's server sends none of its own),
  :meth:`ProviderPlugin.admin_routes`, :meth:`ProviderPlugin.admin_pages`,
  and :meth:`ProviderPlugin.cli_commands`.

The pipeline (:mod:`polyweb_provider_mock.pipeline`) owns everything that is
common: fault rules, authentication against the key table, keyless budgets,
credit checks, the request log and its secret redaction, and malformed-body
faults. A handler only validates the request, calls
:meth:`OperationContext.charge` (or :meth:`OperationContext.charge_all` for a
request billed in parts) for billed work, spends any provider rate windows
with :meth:`OperationContext.admit`, and builds the body.
``polyweb_provider_mock/providers/tavily.py`` is the reference implementation.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar, Literal

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response

from polyweb_provider_mock import content
from polyweb_provider_mock.access import AdminAccess
from polyweb_provider_mock.models import Account, Fixture, KeyFormat, PriceRule, ProviderSeed
from polyweb_provider_mock.store import Charge, MockStore, Principal
from polyweb_provider_mock.windows import Window, WindowSpec

__all__ = [
    "Credentials",
    "ErrorContext",
    "ErrorKind",
    "Handler",
    "MockResponse",
    "Operation",
    "OperationContext",
    "ProviderPlugin",
    "bearer_token",
    "header_value",
    "kind_for_status",
]


class ErrorKind(StrEnum):
    """Provider error situations that every plugin renders in its real format."""

    AUTH_INVALID = "auth_invalid"
    AUTH_REVOKED = "auth_revoked"
    FORBIDDEN = "forbidden"
    BAD_REQUEST = "bad_request"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    SERVER_ERROR = "server_error"
    SERVICE_UNAVAILABLE = "service_unavailable"


def kind_for_status(status: int) -> ErrorKind:
    """Return the error kind that an arbitrary HTTP status represents."""

    if status == 401:
        return ErrorKind.AUTH_INVALID
    if status == 402:
        return ErrorKind.QUOTA_EXHAUSTED
    if status == 403:
        return ErrorKind.FORBIDDEN
    if status == 429:
        return ErrorKind.RATE_LIMITED
    if status == 503:
        return ErrorKind.SERVICE_UNAVAILABLE
    if 400 <= status < 500:
        return ErrorKind.BAD_REQUEST
    return ErrorKind.SERVER_ERROR


@dataclass(frozen=True)
class ErrorContext:
    """Facts an error builder can use.

    ``status`` overrides the provider's default status for the kind (for
    example an ``http_error`` fault with status 502). ``scope`` names what is
    exhausted (``account``, ``key``, ``paygo``) or which keyless window
    applies (``day``, ``minute``). ``missing_key`` separates an absent key
    from a wrong one, for providers that answer them differently.

    The pipeline also fills ``store``, ``account`` (of the presented key, when
    it resolved), ``request``, and ``presented_key`` (the value that
    :meth:`ProviderPlugin.credentials` returned), so an error can carry
    ledger-based headers or word a malformed key differently. Never echo
    ``presented_key`` into a response.
    """

    operation: str
    status: int | None = None
    message: str | None = None
    retry_after: int | None = None
    retry_after_header: bool = True
    keyless: bool = False
    missing_key: bool = False
    scope: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    store: MockStore | None = field(default=None, compare=False, repr=False)
    account: Account | None = field(default=None, compare=False, repr=False)
    request: Request | None = field(default=None, compare=False, repr=False)
    presented_key: str | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Credentials:
    """What a request presents: a key value (or none) and a keyless request."""

    key: str | None
    keyless: bool = False


@dataclass
class MockResponse:
    """A provider response: JSON-ready ``body`` (or raw bytes), status, headers."""

    status: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    media_type: str = "application/json"

    def content(self) -> bytes:
        if isinstance(self.body, bytes):
            return self.body
        return json.dumps(self.body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def to_response(self, extra_headers: Mapping[str, str] | None = None) -> Response:
        headers = {**(extra_headers or {}), **self.headers}
        return Response(
            content=self.content(),
            status_code=self.status,
            headers=headers,
            media_type=self.media_type,
        )


Handler = Callable[["OperationContext"], Awaitable[MockResponse]]


@dataclass(frozen=True)
class Operation:
    """One provider endpoint.

    ``path`` uses Starlette syntax (``/v1/items/{item_id}``). ``name`` is the
    operation that fault rules, the log, and fixtures use. ``billable``
    operations accept ``quota_exhausted`` faults. ``keyless`` operations
    accept a request whose :class:`Credentials` ask for keyless mode.
    ``auth="none"`` skips key checks (for example OAuth endpoints). A
    non-empty ``scopes`` needs a key that holds one of them. A non-empty
    ``hosts`` serves the path on those plugin hosts only; on another host the
    path does not exist (:meth:`ProviderPlugin.not_found` answers), so two
    hosts can serve different operations on one path.
    ``log_body=False`` keeps the request and response bodies out of the
    request log, for operations that carry tokens or minted keys.
    """

    name: str
    method: str
    path: str
    handler: Handler
    billable: bool = True
    keyless: bool = False
    auth: Literal["key", "none"] = "key"
    scopes: frozenset[str] = frozenset()
    hosts: frozenset[str] = frozenset()
    log_body: bool = True


class OperationContext:
    """Everything a handler needs for one request."""

    def __init__(
        self,
        *,
        plugin: "ProviderPlugin",
        operation: Operation,
        request: Request,
        raw_body: bytes,
        principal: Principal,
        store: MockStore,
        sequence: int,
        credentials: Credentials | None = None,
    ) -> None:
        self.plugin = plugin
        self.operation = operation
        self.request = request
        self.raw_body = raw_body
        self.principal = principal
        self.store = store
        self.sequence = sequence
        self.credentials = credentials or Credentials(key=None)
        #: Set by the handler to the normalized query or URL it answered.
        self.match_key: str | None = None
        self.charges: list[Charge] = []

    def json(self) -> Any:
        """Parse the request body; raises ``json.JSONDecodeError`` on bad JSON."""

        return json.loads(self.raw_body or b"null")

    def charge(self, operation: str, units: int | Decimal = 1) -> Charge:
        """Debit a priced operation; raises ``QuotaExhausted`` without funds."""

        result = self.store.charge(self.principal, operation, Decimal(units))
        self.charges.append(result)
        return result

    def charge_all(self, parts: Sequence[tuple[str, int | Decimal]]) -> list[Charge]:
        """Debit the priced parts of one request, all or nothing.

        Raises ``QuotaExhausted`` (and debits nothing) when the whole cost
        exceeds the allowance; see :meth:`MockStore.charge_all`.
        """

        result = self.store.charge_all(self.principal, parts)
        self.charges.extend(result)
        return result

    def admit(
        self, specs: Sequence[WindowSpec], units: int = 1
    ) -> tuple[Window | None, list[Window]]:
        """Spend ``units`` in every rate window, or in none; see :meth:`MockStore.admit_windows`."""

        return self.store.admit_windows(specs, units)

    def fixture(self, match_key: str, operation: str | None = None) -> Fixture | None:
        """Return a saved fixture for this operation and match key."""

        return self.store.fixture(self.plugin.name, operation or self.operation.name, match_key)

    def error_context(self, **values: Any) -> ErrorContext:
        """Return an :class:`ErrorContext` for this request with the pipeline facts filled."""

        values.setdefault("keyless", self.principal.keyless)
        values.setdefault("store", self.store)
        values.setdefault("account", self.principal.account)
        values.setdefault("request", self.request)
        values.setdefault("presented_key", self.credentials.key)
        return ErrorContext(operation=self.operation.name, **values)

    def error(self, kind: ErrorKind, **values: Any) -> MockResponse:
        """Render a provider error for this operation."""

        return self.plugin.error(kind, self.error_context(**values))

    def request_id(self) -> str:
        """Return a UUID-shaped request ID that is unique per mock request."""

        return content.stable_uuid(self.plugin.name, "request", self.sequence)


def bearer_token(request: Request) -> str | None:
    """Return the token of an ``Authorization: Bearer`` header, if any."""

    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def header_value(request: Request, name: str) -> str | None:
    """Return a stripped, non-empty header value."""

    value = request.headers.get(name)
    return value.strip() if value and value.strip() else None


class ProviderPlugin(ABC):
    """Base class of one impersonated provider; see the module docstring."""

    name: ClassVar[str]
    hosts: ClassVar[frozenset[str]]
    key_format: ClassVar[KeyFormat] = KeyFormat()

    @abstractmethod
    def operations(self) -> Sequence[Operation]:
        """Return every endpoint the provider serves."""

    @abstractmethod
    def credentials(self, request: Request, store: MockStore) -> Credentials:
        """Return the key a request presents and whether it asks for keyless mode.

        ``store`` gives read access to state and the mock clock (``store.now``),
        for providers whose credential is a token that maps to a key.
        """

    @abstractmethod
    def default_seed(self) -> ProviderSeed:
        """Return the accounts, keys, and keyless setting that ``seed`` creates."""

    @abstractmethod
    def default_pricing(self) -> Sequence[PriceRule]:
        """Return the default price of every billed operation."""

    @abstractmethod
    def error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        """Return the provider's real response for one error kind."""

    def response_headers(self) -> dict[str, str]:
        """Return headers the provider adds to every response.

        The mock's HTTP server sends no ``Server`` header, so a plugin sets
        the provider's real one here (or per response) when it has one.
        """

        return {}

    def admin_routes(self, router: APIRouter, store: MockStore, access: AdminAccess) -> None:
        """Add provider-specific admin routes; use paths under ``/<name>/``.

        ``router`` has the ``/_mock`` prefix and the admin token guard;
        ``access`` can remember a token posted by a page form in the admin
        cookie. The default adds nothing.
        """

        return

    def admin_pages(self, router: APIRouter, store: MockStore, access: AdminAccess) -> None:
        """Add browser pages under ``/_mock/<name>/`` that need no admin token.

        A page may only render (for example a form that posts to a guarded
        route of :meth:`admin_routes`). When ``access.required``, the page
        should offer an ``admin_token`` field or remember a valid
        ``?admin_token=`` with :meth:`AdminAccess.remember`. The default adds
        nothing.
        """

        return

    def cli_commands(self, groups: Any) -> None:
        """Add a ``polyweb-mock <name> ...`` command group to the argparse ``groups``.

        Each leaf parser sets ``handler=(args, store) -> printable result``,
        as the core commands do. The default adds nothing.
        """

        return

    def not_found(self, request: Request, status: int) -> MockResponse:
        """Return the provider's response to an unknown path or method."""

        detail = "Method Not Allowed" if status == 405 else "Not Found"
        return MockResponse(status=status, body={"detail": detail})

    def drop_required_field(self, operation: str, body: Any) -> Any:
        """Return ``body`` without a field the client needs (``malformed`` fault)."""

        if not isinstance(body, dict) or not body:
            return {}
        victim = "results" if "results" in body else next(iter(body))
        return {key: value for key, value in body.items() if key != victim}
