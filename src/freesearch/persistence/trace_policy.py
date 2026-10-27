"""Trace-policy projection for persisted span rows (TASK-000044).

The trace policy is resolved once at the trusted execution boundary and its
immutable decision (sampled, captures payload) is stamped on every span it
opens, children included. This module only projects an already-decided row:

* the exporter drops a span whose stamped decision is unsampled,
* metadata-only capture keeps timing, provider, outcome, counts, and span
  metadata, and never request/response content,
* the raw :func:`freesearch.persistence.otel_exporter.write_trace_spans` seed
  path can still write fixture rows directly.

Resolving policy here, at flush time, would let a settings edit retroactively
capture an in-flight trace and could split one trace's sampling decision across
batches, so this module never reads settings.
"""

from __future__ import annotations

from typing import Final

from freesearch.models.observability import (
    TRACE_CONTENT_ATTRIBUTES,
    TRACE_SAFE_EVENT_ATTRIBUTES,
    TraceEventDetail,
    TraceSpanRecord,
    trace_is_sampled,
)
from freesearch.models.projects import ProjectTracePolicy, TraceDetailPolicy

#: Policy used when a record has no capture decision: metadata only.
METADATA_ONLY_POLICY: Final[ProjectTracePolicy] = ProjectTracePolicy(
    sampling_rate=1.0,
    detail=TraceDetailPolicy.METADATA,
)


def _metadata_only(record: TraceSpanRecord) -> TraceSpanRecord:
    """Drop payload content from one projected span row."""

    return record.model_copy(
        update={
            "input_text": None,
            "output_json": None,
            "attributes": {
                key: value
                for key, value in record.attributes.items()
                if key not in TRACE_CONTENT_ATTRIBUTES
            },
            "events": [
                TraceEventDetail(
                    name=event.name,
                    timestamp=event.timestamp,
                    attributes={
                        key: value
                        for key, value in event.attributes.items()
                        if key in TRACE_SAFE_EVENT_ATTRIBUTES
                    },
                )
                for event in record.events
            ],
        }
    )


def apply_trace_policy(record: TraceSpanRecord, policy: ProjectTracePolicy) -> TraceSpanRecord:
    """Return the record as the project's detail and redaction policy allows."""

    if policy.captures_payload:
        return record
    return _metadata_only(record)


__all__ = [
    "METADATA_ONLY_POLICY",
    "apply_trace_policy",
    "trace_is_sampled",
]
