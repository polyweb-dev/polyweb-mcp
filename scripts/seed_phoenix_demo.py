#!/usr/bin/env python3
"""Generate synthetic OTLP traces for a Phoenix demo. Reruns append demo data in Phoenix.

Examples:
  python scripts/seed_phoenix_demo.py --output phoenix-demo.json
  uv run --no-project --with opentelemetry-proto scripts/seed_phoenix_demo.py --endpoint http://localhost:6006

Upload reads PHOENIX_API_KEY from the environment. JSON generation uses only stdlib.
"""

import argparse
import base64
import json
import os
import random
import secrets
import sys
import time
import urllib.request

MIME = "application/json"


def attr(key, value):
    if isinstance(value, bool):
        v = {"boolValue": value}
    elif isinstance(value, int):
        v = {"intValue": str(value)}
    elif isinstance(value, float):
        v = {"doubleValue": value}
    else:
        v = {"stringValue": str(value)}
    return {"key": key, "value": v}


def attrs(values):
    return [attr(k, v) for k, v in values.items()]


def encode_otlp(payload):
    """Encode using public OTLP messages; no Phoenix package or source required."""
    try:
        from google.protobuf.json_format import ParseDict
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
    except ImportError as error:
        raise RuntimeError("Upload requires opentelemetry-proto; see --help example") from error
    # Protobuf's generic JSON parser uses base64 bytes, whereas OTLP JSON IDs are hex.
    document = json.loads(json.dumps(payload))
    for resource in document["resourceSpans"]:
        for scope in resource["scopeSpans"]:
            for span in scope["spans"]:
                for field in ("traceId", "spanId", "parentSpanId"):
                    if field in span:
                        span[field] = base64.b64encode(bytes.fromhex(span[field])).decode("ascii")
    return ParseDict(document, ExportTraceServiceRequest()).SerializeToString()


def build_payload(project="freesearch-ui-audit-demo", count=40, now_ns=None, seed=None):
    """Build a standard OTLP ExportTraceServiceRequest with deterministic layouts."""
    if not 1 <= count <= 500:
        raise ValueError("count must be between 1 and 500")
    rng = random.Random(seed)
    now_ns = now_ns or time.time_ns()
    spans = []
    cases = ["success", "search", "fetch", "fallback", "parallel", "error"]
    for i in range(count):
        trace_id = secrets.token_hex(16)
        base = now_ns - 5_000_000_000 - (count - 1 - i) * 135_000_000_000
        duration = rng.randint(350, 1800) * 1_000_000
        root_id = secrets.token_hex(8)
        case = "parallel" if i == count - 1 else cases[i % len(cases)]
        q = {"query": f"demo topic {i + 1}", "limit": 3}
        if case == "fetch":
            q = {"url": f"https://example.com/demo/{i + 1}"}
        results = [
            {
                "title": f"Example result {j + 1}",
                "url": f"https://example.{('com' if j % 2 == 0 else 'org')}/demo/{i + 1}/{j + 1}",
            }
            for j in range(3)
        ]

        def make(
            name,
            sid,
            parent,
            start,
            dur,
            kind,
            inp,
            out,
            status="OK",
            extra=None,
            exception=None,
            trace_id=trace_id,
            index=i,
        ):
            a = {
                "openinference.span.kind": kind,
                "input.value": json.dumps(inp),
                "input.mime_type": MIME,
                "output.value": json.dumps(out),
                "output.mime_type": MIME,
                "session.id": f"demo-session-{index % 9 + 1:02d}",
                "user.id": f"demo-user-{index % 7 + 1:02d}",
                "demo.synthetic": True,
                "demo.dataset": "phoenix-observability-demo",
            }
            if extra:
                a.update(extra)
            s = {
                "traceId": trace_id,
                "spanId": sid,
                "name": name,
                "kind": 1,
                "startTimeUnixNano": str(start),
                "endTimeUnixNano": str(start + dur),
                "attributes": attrs(a),
                "status": {"code": 2 if status == "ERROR" else 1},
            }
            if parent:
                s["parentSpanId"] = parent
            if exception:
                s["status"]["message"] = exception
                s["events"] = [
                    {
                        "name": "exception",
                        "timeUnixNano": str(start + dur),
                        "attributes": attrs(
                            {
                                "exception.type": "RuntimeError",
                                "exception.message": exception,
                                "exception.stacktrace": "synthetic demo error",
                            }
                        ),
                    }
                ]
            spans.append(s)

        make(
            f"freesearch.{case}",
            root_id,
            None,
            base,
            duration,
            "CHAIN",
            q,
            {"error": "Synthetic provider failure"} if case == "error" else {"results": results},
            status="ERROR" if case == "error" else "OK",
            extra={"openinference.project.name": project, "demo.scenario": case},
            exception="Synthetic provider failure" if case == "error" else None,
        )
        for label, kind, frac, err in [
            ("search", "RETRIEVER", 0.45, case in ("error", "fallback")),
            ("fetch", "TOOL", 0.35, False),
        ]:
            sid = secrets.token_hex(8)
            make(
                f"freesearch.{label}",
                sid,
                root_id,
                base + int(duration * 0.1),
                int(duration * frac),
                kind,
                q if label == "search" else {"url": results[0]["url"]},
                {"error": "Synthetic provider failure"}
                if err
                else (
                    {"results": results}
                    if label == "search"
                    else {"text": "Synthetic fetched document"}
                ),
                "ERROR" if err else "OK",
                {"demo.attempt": 1, "demo.provider": "demo-provider-a"},
                "synthetic search failure" if err else None,
            )
        if case == "fallback":
            make(
                "freesearch.fallback",
                secrets.token_hex(8),
                root_id,
                base + int(duration * 0.55),
                int(duration * 0.25),
                "RETRIEVER",
                q,
                {"results": results},
                extra={"demo.fallback": True, "demo.provider": "demo-provider-b"},
            )
        if case == "parallel":
            for n in range(2):
                make(
                    f"freesearch.fanout.{n + 1}",
                    secrets.token_hex(8),
                    root_id,
                    base + int(duration * 0.2),
                    int(duration * 0.25),
                    "TOOL",
                    q,
                    {"url": results[n]["url"]},
                    extra={"demo.parallel": True},
                )
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": attrs(
                        {
                            "service.name": "FreeSearch synthetic demo",
                            "openinference.project.name": project,
                            "demo.synthetic": True,
                        }
                    )
                },
                "scopeSpans": [{"scope": {"name": "freesearch.synthetic-demo"}, "spans": spans}],
            }
        ]
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default="freesearch-ui-audit-demo")
    p.add_argument("--count", type=int, default=40)
    p.add_argument("--output", help="write JSON file; default stdout")
    p.add_argument(
        "--endpoint", help="explicit Phoenix base URL (POSTs to /v1/traces); no external providers"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="build payload only (default without --endpoint)"
    )
    a = p.parse_args()
    if not 1 <= a.count <= 500:
        p.error("--count must be between 1 and 500")
    payload = build_payload(a.project, a.count)
    data = json.dumps(payload, indent=2)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(data + "\n")
    elif not a.endpoint:
        sys.stdout.write(data + "\n")
    if a.endpoint and not a.dry_run:
        key = os.environ.get("PHOENIX_API_KEY")
        if not key:
            p.error("PHOENIX_API_KEY is required with --endpoint")
        url = a.endpoint.rstrip("/") + "/v1/traces"
        req = urllib.request.Request(
            url,
            data=encode_otlp(payload),
            headers={"Content-Type": "application/x-protobuf", "Authorization": "Bearer " + key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            print(f"Phoenix returned HTTP {response.status}")
    elif a.endpoint and a.dry_run:
        print(f"Dry run: built {a.count} traces; no upload")


if __name__ == "__main__":
    main()
