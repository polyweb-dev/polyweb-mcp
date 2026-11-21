"""The admin token check shared by the ``/_mock`` API and plugin admin pages.

When ``POLYWEB_PROVIDER_MOCK_ADMIN_TOKEN`` is set, an admin request proves the
token with one of:

- ``Authorization: Bearer <token>`` (the CLI-equivalent API, scripts);
- an ``admin_token`` field of a form post (a browser on a plugin page);
- the ``polyweb_mock_admin`` cookie, which a plugin page sets after the token
  arrived once as ``?admin_token=<token>`` on the page itself or in a form.

Plugin pages (:meth:`ProviderPlugin.admin_pages`) are the only unguarded
admin routes; they render forms and must not change state themselves.

The token never appears in a provider response, so a provider client that is
shown a verification URL does not learn it.
"""

import hmac
from dataclasses import dataclass
from typing import Final
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import Response

__all__ = ["COOKIE", "AdminAccess"]

#: Cookie that carries the admin token for browser pages under ``/_mock``.
COOKIE: Final = "polyweb_mock_admin"
_FIELD: Final = "admin_token"


@dataclass(frozen=True)
class AdminAccess:
    """Whether admin requests need a token, and how one is presented."""

    token: str | None = None

    @property
    def required(self) -> bool:
        return self.token is not None

    def _matches(self, value: str | None) -> bool:
        if self.token is None:
            return True
        return value is not None and hmac.compare_digest(value.encode(), self.token.encode())

    def page_token(self, request: Request) -> str | None:
        """Return a valid token given as ``?admin_token=`` (to remember in the cookie)."""

        value = request.query_params.get(_FIELD)
        return value if self.token is not None and self._matches(value) else None

    async def form_token(self, request: Request) -> str | None:
        """Return a valid token posted as the ``admin_token`` form field."""

        if self.token is None or "form-urlencoded" not in request.headers.get("content-type", ""):
            return None
        raw = await request.body()
        values = parse_qs(raw.decode("utf-8", errors="replace")).get(_FIELD, [])
        return values[0] if values and self._matches(values[0]) else None

    async def allowed(self, request: Request) -> bool:
        """Return whether the request proves the token (always, when none is set)."""

        if self.token is None:
            return True
        scheme, _, value = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and self._matches(value.strip()):
            return True
        if self._matches(request.cookies.get(COOKIE)):
            return True
        return await self.form_token(request) is not None

    def remember(self, response: Response, token: str | None) -> Response:
        """Set the admin cookie for ``/_mock`` pages when ``token`` is a valid token."""

        if self.token is not None and token is not None and self._matches(token):
            response.set_cookie(
                COOKIE, token, path="/_mock", httponly=True, samesite="strict", max_age=86400
            )
        return response
