import logging

from freesearch.configuration.config import Settings
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.logging import redact_secrets


def test_settings_load_from_prefixed_environment(monkeypatch) -> None:
    monkeypatch.setenv("FREESEARCH_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("FREESEARCH_HTTP_TIMEOUT_SECONDS", "12")

    settings = Settings()

    assert settings.log_level == "DEBUG"
    assert settings.http_timeout_seconds == 12


def test_http_client_uses_shared_settings() -> None:
    settings = Settings(user_agent="test-agent", http_timeout_seconds=9)
    client = create_async_client(settings)

    try:
        assert client.headers["user-agent"] == "test-agent"
        assert client.timeout.read == 9
        assert client.timeout.connect == settings.http_connect_timeout_seconds
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_redaction_masks_known_and_named_secrets() -> None:
    assert (
        redact_secrets("key=abc token=xyz", secrets=("abc",)) == "key=[REDACTED] token=[REDACTED]"
    )
    assert redact_secrets("api_key='abc123'") == "api_key=[REDACTED]"


def test_logging_configuration_has_a_redaction_filter() -> None:
    from freesearch.infrastructure.logging import SecretRedactionFilter

    record = logging.LogRecord("test", logging.INFO, "", 0, "secret=%s", ("value",), None)
    filter_ = SecretRedactionFilter(("value",))

    assert filter_.filter(record)
    assert record.args == ("[REDACTED]",)
