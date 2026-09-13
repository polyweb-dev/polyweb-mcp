"""Unit coverage for :class:`BorrowedTransport` timeout/lifecycle policy.

Characterizes the borrowed-transport policy difference that slice 2.3 must
keep explicit: Tavily/You.com reassert the shared client's phase-specific
timeout onto each request (so an SDK-stamped scalar never collapses the
connect/read/write/pool policy), while Parallel delegates without that step.
Also pins the lifecycle contract: the transport never owns the shared
client — closing the transport (or an adapter-owned client built over it)
leaves the shared client open and usable.
"""

import inspect

import httpx
import pytest

from freesearch.infrastructure.borrowed_transport import BorrowedTransport

_PHASES = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=20.0)
_SCALAR_STAMP = 60.0  # what an SDK per-call timeout stamps onto the request


class _WireRecorder:
    """Shared ``httpx.MockTransport`` handler recording wire requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"ok": True})


def _shared_client(recorder: _WireRecorder) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(recorder),
        timeout=_PHASES,
    )


def _stamped_request() -> httpx.Request:
    """A request carrying an SDK-stamped scalar timeout, pre-reassertion."""
    return httpx.Request(
        "GET",
        "https://api.example.com/search",
        extensions={"timeout": _SCALAR_STAMP},
    )


async def test_reassert_true_overwrites_scalar_stamp_with_shared_phases() -> None:
    recorder = _WireRecorder()
    shared = _shared_client(recorder)
    try:
        transport = BorrowedTransport(shared, reassert_timeout=True)
        response = await transport.handle_async_request(_stamped_request())
    finally:
        await shared.aclose()

    assert response.status_code == 200
    assert recorder.requests[0].extensions["timeout"] == _PHASES.as_dict()


async def test_reassert_false_preserves_scalar_stamp_plain_delegation() -> None:
    recorder = _WireRecorder()
    shared = _shared_client(recorder)
    try:
        transport = BorrowedTransport(shared, reassert_timeout=False)
        response = await transport.handle_async_request(_stamped_request())
    finally:
        await shared.aclose()

    assert response.status_code == 200
    # Plain delegation: the SDK-stamped scalar passes through untouched.
    assert recorder.requests[0].extensions["timeout"] == _SCALAR_STAMP


async def test_both_policies_delegate_response_through_shared_pool() -> None:
    for reassert in (True, False):
        recorder = _WireRecorder()
        shared = _shared_client(recorder)
        try:
            transport = BorrowedTransport(shared, reassert_timeout=reassert)
            response = await transport.handle_async_request(
                httpx.Request("GET", "https://api.example.com/search")
            )
        finally:
            await shared.aclose()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert len(recorder.requests) == 1


async def test_transport_close_is_noop_shared_stays_open_and_usable() -> None:
    recorder = _WireRecorder()
    shared = _shared_client(recorder)
    try:
        transport = BorrowedTransport(shared, reassert_timeout=True)
        await transport.aclose()

        assert shared.is_closed is False
        assert (await shared.get("https://api.example.com/search")).status_code == 200
    finally:
        await shared.aclose()


async def test_owned_client_close_leaves_shared_client_open_and_usable() -> None:
    recorder = _WireRecorder()
    shared = _shared_client(recorder)
    try:
        owned = httpx.AsyncClient(
            transport=BorrowedTransport(shared, reassert_timeout=False),
            timeout=shared.timeout,
        )
        await owned.aclose()

        assert owned.is_closed is True
        assert shared.is_closed is False
        assert (await shared.get("https://api.example.com/search")).status_code == 200
    finally:
        await shared.aclose()


def test_timeout_policy_is_explicit_required_kwarg() -> None:
    """The policy difference must stay explicit: no silent default."""
    signature = inspect.signature(BorrowedTransport.__init__)
    parameter = signature.parameters["reassert_timeout"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        BorrowedTransport(httpx.AsyncClient())  # type: ignore[call-arg]
