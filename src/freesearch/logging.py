"""Small standard-library logging setup with secret redaction."""

import logging
import re
from collections.abc import Iterable

_SENSITIVE_FIELD_RE = re.compile(
    r"(?P<field>\b(?:api[_-]?key|authorization|password|secret|token)\b)"
    r"(?P<separator>\s*[:=]\s*)(?P<quote>[\"']?)(?P<value>[^\s,;\"']+)"
    r"(?P=quote)",
    re.IGNORECASE,
)


def redact_secrets(value: object, secrets: Iterable[str] = ()) -> str:
    """Return a log-safe string with known values and secret-like fields masked."""

    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")

    return _SENSITIVE_FIELD_RE.sub(
        lambda match: f"{match.group('field')}{match.group('separator')}[REDACTED]",
        text,
    )


class SecretRedactionFilter(logging.Filter):
    """Redact configured secrets and common credential fields in log records."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.msg, self._secrets)
        if record.args:
            record.args = tuple(redact_secrets(arg, self._secrets) for arg in record.args)
        return True


def configure_logging(level: str = "INFO", secrets: Iterable[str] = ()) -> None:
    """Configure the root logger once for local use and tests."""

    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactionFilter(secrets))
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
