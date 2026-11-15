from typing import Any
from uuid import uuid4

from pydantic import SecretStr

from polyweb.infrastructure.observability_asgi import trusted_trace_parent
from polyweb.models.projects import ProjectApiKeyPrincipal
from polyweb.services.execution_forward import ExecutionForwarder


def test_forwarded_trace_uses_verified_project_with_omitted_body_project() -> None:
    project_id = uuid4()
    trace_id, span_id = "1" * 32, "2" * 16
    headers, _ = ExecutionForwarder._forward_request_headers(
        "/search",
        {"query": "example"},
        credential=SecretStr("secret"),
        project_id=project_id,
        trace_id=trace_id,
        parent_span_id=span_id,
        deadline_ms=None,
    )
    principal = ProjectApiKeyPrincipal(
        api_key_id=uuid4(), project_id=project_id, scopes=frozenset({"search.execute"})
    )
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/search",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "state": {"user": principal, "forwarding_credential": "secret"},
    }
    assert trusted_trace_parent(scope) == (trace_id, span_id)
    scope["state"]["user"] = principal.model_copy(update={"project_id": uuid4()})
    assert trusted_trace_parent(scope) is None
