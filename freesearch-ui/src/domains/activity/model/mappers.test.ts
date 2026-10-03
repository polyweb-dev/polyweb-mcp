import { describe, expect, it } from "vitest"
import {
  TraceDecodeError,
  mapTraceDetail,
  mapTraceList,
  mapTraceSummary,
} from "./mappers"
import {
  ERROR_TRACE_ID,
  SUCCESS_TRACE_ID,
  errorTraceDetailFixture,
  errorTraceSummaryFixture,
  traceDetailFixture,
  traceListFixture,
  traceSummaryFixture,
} from "@/test/fixtures/activity"

/**
 * Wire -> domain decoding for the Activity trace read API. The list must stay
 * payload-free (no query/results rows leak through), unknown operations are
 * preserved as null rather than coerced to Search, malformed rows are dropped
 * from the list, and an unusable detail payload raises TraceDecodeError.
 */
describe("mapTraceSummary", () => {
  it("decodes a valid search summary row", () => {
    const summary = mapTraceSummary(traceSummaryFixture())

    expect(summary).toMatchObject({
      traceId: SUCCESS_TRACE_ID,
      operation: "search",
      startedAt: "2026-09-29T09:15:00.000000Z",
      durationMs: 248,
      provider: "keenable",
      providerLabel: "Keenable",
      outcome: "success",
      resultCount: 2,
      error: null,
    })
  })

  it("decodes a valid fetch error summary row", () => {
    const summary = mapTraceSummary(errorTraceSummaryFixture())

    expect(summary).toMatchObject({
      traceId: ERROR_TRACE_ID,
      operation: "fetch",
      outcome: "error",
      resultCount: null,
      error: { type: "http_error", message: "HTTP 502" },
    })
  })

  it("preserves unknown operations as null instead of coercing to Search", () => {
    for (const operation of ["answer", "ANSWER", "Search", "", 42, null]) {
      const summary = mapTraceSummary(traceSummaryFixture({ operation }))
      expect(summary?.operation).toBeNull()
    }
  })

  it("keeps search and fetch operations intact", () => {
    expect(mapTraceSummary(traceSummaryFixture({ operation: "search" }))?.operation).toBe(
      "search"
    )
    expect(
      mapTraceSummary(traceSummaryFixture({ operation: "fetch" }))?.operation
    ).toBe("fetch")
  })

  it("rejects non-canonical trace identifiers", () => {
    for (const trace_id of [
      "not-a-trace-id",
      "E1C2D3A4B5C6D7E8F9012345678ABCDE",
      "e1c2d3a4",
      "",
      null,
      123,
    ]) {
      expect(mapTraceSummary(traceSummaryFixture({ trace_id }))).toBeNull()
    }
  })

  it("rejects rows with unusable timing", () => {
    expect(mapTraceSummary(traceSummaryFixture({ started_at: "yesterday" }))).toBeNull()
    expect(mapTraceSummary(traceSummaryFixture({ started_at: null }))).toBeNull()
    expect(mapTraceSummary(traceSummaryFixture({ duration_ms: -5 }))).toBeNull()
    expect(mapTraceSummary(traceSummaryFixture({ duration_ms: Number.NaN }))).toBeNull()
    expect(mapTraceSummary(traceSummaryFixture({ duration_ms: "248" }))).toBeNull()
    expect(mapTraceSummary(traceSummaryFixture({ duration_ms: null }))).toBeNull()
  })

  it("rejects non-object payloads", () => {
    for (const payload of [null, undefined, [], "trace", 42]) {
      expect(mapTraceSummary(payload)).toBeNull()
    }
  })

  it("labels a missing provider with an em dash and aggregates explicitly", () => {
    expect(mapTraceSummary(traceSummaryFixture({ provider: null }))?.providerLabel).toBe(
      "—"
    )
    expect(mapTraceSummary(traceSummaryFixture({ provider: "" }))?.providerLabel).toBe(
      "—"
    )
    expect(
      mapTraceSummary(traceSummaryFixture({ provider: "aggregated" }))?.providerLabel
    ).toBe("All providers")
  })

  it("falls back to error for unknown outcomes", () => {
    expect(mapTraceSummary(traceSummaryFixture({ outcome: "bogus" }))?.outcome).toBe(
      "error"
    )
  })
})

describe("mapTraceList", () => {
  it("decodes the list payload with newest-first rows", () => {
    const summaries = mapTraceList(traceListFixture())

    expect(summaries).toHaveLength(2)
    expect(summaries[0]?.traceId).toBe(SUCCESS_TRACE_ID)
    expect(summaries[1]?.traceId).toBe(ERROR_TRACE_ID)
  })

  it("drops malformed rows while keeping usable ones", () => {
    const summaries = mapTraceList({
      items: [
        traceSummaryFixture(),
        { trace_id: "junk", operation: "search" },
        null,
        "row",
        traceSummaryFixture({ trace_id: "zz".padEnd(32, "z"), duration_ms: -1 }),
        errorTraceSummaryFixture(),
      ],
      generated_at: "2026-09-29T09:25:00.000000Z",
    })

    expect(summaries.map((summary) => summary.traceId)).toEqual([
      SUCCESS_TRACE_ID,
      ERROR_TRACE_ID,
    ])
  })

  it("decodes an empty list to an empty array", () => {
    expect(mapTraceList({ items: [], generated_at: "x" })).toEqual([])
  })

  it("throws TraceDecodeError when the payload has no list", () => {
    for (const payload of [{}, { items: "nope" }, { items: null }, null, []]) {
      expect(() => mapTraceList(payload)).toThrow(TraceDecodeError)
    }
  })
})

describe("mapTraceDetail", () => {
  it("decodes search detail with input, results, and ordered stages", () => {
    const detail = mapTraceDetail(traceDetailFixture())

    expect(detail.traceId).toBe(SUCCESS_TRACE_ID)
    expect(detail.input).toBe("distributed consensus algorithms")
    expect(detail.output?.kind).toBe("search_results")
    if (detail.output?.kind === "search_results") {
      expect(detail.output.query).toBe("distributed consensus algorithms")
      expect(detail.output.results).toHaveLength(2)
      expect(detail.output.results[0]).toMatchObject({
        title: "Consensus algorithms explained",
        url: "https://docs.freesearch.dev/consensus",
        snippet: "Raft, Paxos, and where each applies.",
        source: "keenable",
        score: 0.94,
      })
    }
    expect(detail.stages.map((stage) => stage.name)).toEqual([
      "POST /search",
      "freesearch.backend",
      "freesearch.provider",
      "freesearch.provider.http",
      "freesearch.provider.parse",
      "freesearch.results",
      "freesearch.response",
    ])
    expect(detail.stages[0]?.durationMs).toBe(248)
    expect(detail.totalMs).toBe(248)
  })

  it("decodes fetch detail with the fetched URL as input", () => {
    const detail = mapTraceDetail(errorTraceDetailFixture())

    expect(detail.traceId).toBe(ERROR_TRACE_ID)
    expect(detail.operation).toBe("fetch")
    expect(detail.input).toBe("https://docs.freesearch.dev/getting-started")
    expect(detail.output).toBeNull()
    expect(detail.error).toMatchObject({ type: "http_error", message: "HTTP 502" })
    expect(detail.stages).toHaveLength(2)
    expect(detail.stages[1]?.error).toMatchObject({
      type: "http_error",
      message: "HTTP 502",
    })
    expect(detail.stages[1]?.events.map((event) => event.name)).toEqual(["exception"])
  })

  it("throws TraceDecodeError for an unusable detail payload", () => {
    expect(() => mapTraceDetail({})).toThrow(TraceDecodeError)
    expect(() => mapTraceDetail(null)).toThrow(TraceDecodeError)
    expect(() => mapTraceDetail(traceDetailFixture({ trace_id: "bad" }))).toThrow(
      TraceDecodeError
    )
    expect(() => mapTraceDetail(traceDetailFixture({ started_at: "never" }))).toThrow(
      TraceDecodeError
    )
    expect(() => mapTraceDetail(traceDetailFixture({ duration_ms: -1 }))).toThrow(
      TraceDecodeError
    )
  })

  it("decodes fetch_document output with content length", () => {
    const detail = mapTraceDetail(
      traceDetailFixture({
        operation: "fetch",
        input: "https://example.com/doc",
        output: {
          kind: "fetch_document",
          url: "https://example.com/doc",
          title: "Doc",
          content: "hello world",
          content_length: 11,
          truncated: false,
        },
      })
    )

    expect(detail.output).toMatchObject({
      kind: "fetch_document",
      url: "https://example.com/doc",
      contentLength: 11,
      truncated: false,
    })
  })

  it("maps unknown output shapes to null instead of fabricating results", () => {
    expect(
      mapTraceDetail(traceDetailFixture({ output: { kind: "answer_text" } })).output
    ).toBeNull()
    expect(mapTraceDetail(traceDetailFixture({ output: null })).output).toBeNull()
    expect(mapTraceDetail(traceDetailFixture({ output: "results" })).output).toBeNull()
  })

  it("drops results without a URL and defaults missing fields", () => {
    const detail = mapTraceDetail(
      traceDetailFixture({
        output: {
          kind: "search_results",
          query: "q",
          results: [
            { title: "No URL here" },
            {
              title: "Has URL",
              url: "https://example.com/a",
            },
          ],
        },
      })
    )

    if (detail.output?.kind !== "search_results") throw new Error("expected search output")
    expect(detail.output.results).toHaveLength(1)
    expect(detail.output.results[0]).toMatchObject({
      title: "Has URL",
      url: "https://example.com/a",
      snippet: "",
      source: null,
      score: null,
    })
  })

  it("drops stages with invalid span ids and measures offsets from the trace start", () => {
    const detail = mapTraceDetail(
      traceDetailFixture({
        spans: [
          {
            span_id: "bogus",
            parent_span_id: null,
            name: "POST /search",
            stage: "Search request",
            kind: "server",
            started_at: "2026-09-29T09:15:00.000000Z",
            duration_ms: 10,
            outcome: "success",
            error: null,
            events: [],
          },
          {
            span_id: "aabbccddeeff0011",
            parent_span_id: null,
            name: "POST /search",
            stage: "Search request",
            kind: "server",
            started_at: "2026-09-29T09:15:00.100000Z",
            duration_ms: 10,
            outcome: "success",
            error: null,
            events: [],
          },
        ],
      })
    )

    expect(detail.stages).toHaveLength(1)
    expect(detail.stages[0]?.offsetMs).toBe(100)
  })

  it("keeps parallel provider spans overlapping instead of sequential", () => {
    const detail = mapTraceDetail(
      traceDetailFixture({
        outcome: "partial",
        spans: [
          {
            span_id: "aabbccddeeff0011",
            parent_span_id: null,
            name: "POST /search",
            stage: "Search request",
            kind: "server",
            started_at: "2026-09-29T09:15:00.000000Z",
            duration_ms: 200,
            outcome: "partial",
            error: null,
            events: [],
          },
          {
            span_id: "aabbccddeeff0022",
            parent_span_id: "aabbccddeeff0011",
            name: "freesearch.provider",
            stage: "Provider request",
            kind: "client",
            started_at: "2026-09-29T09:15:00.010000Z",
            duration_ms: 150,
            outcome: "success",
            error: null,
            events: [],
          },
          {
            span_id: "aabbccddeeff0033",
            parent_span_id: "aabbccddeeff0011",
            name: "freesearch.provider",
            stage: "Provider request",
            kind: "client",
            started_at: "2026-09-29T09:15:00.012000Z",
            duration_ms: 150,
            outcome: "error",
            error: { type: "http_error", message: "HTTP 502" },
            events: [],
          },
        ],
      })
    )

    expect(detail.outcome).toBe("partial")
    expect(detail.stages[1]?.offsetMs).toBe(10)
    expect(detail.stages[2]?.offsetMs).toBe(12)
    expect(detail.stages[2]?.error).toMatchObject({ type: "http_error" })
  })
})
