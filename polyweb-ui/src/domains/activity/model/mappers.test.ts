import { describe, expect, it } from "vitest"
import {
  TraceDecodeError,
  mapTraceDetail,
  mapTraceList,
  mapTracePage,
  mapTraceSummary,
} from "./mappers"
import {
  AGGREGATED_TRACE_ID,
  ERROR_TRACE_ID,
  SUCCESS_TRACE_ID,
  aggregatedTraceDetailFixture,
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

    expect(summaries).toHaveLength(3)
    expect(summaries[0]?.traceId).toBe(AGGREGATED_TRACE_ID)
    expect(summaries[1]?.traceId).toBe(SUCCESS_TRACE_ID)
    expect(summaries[2]?.traceId).toBe(ERROR_TRACE_ID)
  })

  it("labels the aggregated row as All providers", () => {
    const summaries = mapTraceList(traceListFixture())

    expect(summaries[0]?.provider).toBe("aggregated")
    expect(summaries[0]?.providerLabel).toBe("All providers")
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

describe("mapTracePage", () => {
  it("keeps the opaque next cursor beside the decoded rows", () => {
    const page = mapTracePage(traceListFixture({ next_cursor: "opaque" }))
    expect(page.items).toHaveLength(3)
    expect(page.nextCursor).toBe("opaque")
  })

  it("reads a missing, null, or empty cursor as the last page", () => {
    expect(mapTracePage(traceListFixture()).nextCursor).toBeNull()
    expect(mapTracePage(traceListFixture({ next_cursor: null })).nextCursor).toBeNull()
    expect(mapTracePage(traceListFixture({ next_cursor: "" })).nextCursor).toBeNull()
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
        url: "https://docs.polyweb.dev/consensus",
        snippet: "Raft, Paxos, and where each applies.",
        source: "keenable",
        score: 0.94,
      })
    }
    expect(detail.stages.map((stage) => stage.name)).toEqual([
      "POST /search",
      "polyweb.backend",
      "polyweb.provider",
      "polyweb.provider.http",
      "polyweb.provider.parse",
      "polyweb.results",
      "polyweb.response",
    ])
    expect(detail.stages[0]?.durationMs).toBe(248)
    expect(detail.totalMs).toBe(248)
  })

  it("decodes fetch detail with the fetched URL as input", () => {
    const detail = mapTraceDetail(errorTraceDetailFixture())

    expect(detail.traceId).toBe(ERROR_TRACE_ID)
    expect(detail.operation).toBe("fetch")
    expect(detail.input).toBe("https://docs.polyweb.dev/getting-started")
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
            name: "polyweb.provider",
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
            name: "polyweb.provider",
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

  it("keeps event attributes structured instead of stringifying them", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const providerStage = detail.stages.find(
      (stage) => stage.name === "polyweb.provider"
    )!

    expect(providerStage).toBeDefined()
    const response = providerStage.events.find(
      (event) => event.name === "polyweb.provider.response"
    )!
    expect(response).toBeDefined()
    expect(response.attributes.result_count).toBe(3)
    expect(response.attributes.results).toHaveLength(3)
    const first = (response.attributes.results as Record<string, unknown>[])[0]!
    expect(first).toMatchObject({ source: "keenable", score: 0.92 })
  })

  it("decodes per-provider response results through the shared result decoder", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const attempts = detail.stages.filter(
      (stage) => stage.name === "polyweb.provider"
    )

    expect(attempts).toHaveLength(7)
    // Malformed entries inside an event payload never leak into the domain.
    const hostile = mapTraceDetail(
      aggregatedTraceDetailFixture({
        spans: (aggregatedTraceDetailFixture().spans as Record<string, unknown>[]).map(
          (span) =>
            span.name === "polyweb.provider"
              ? {
                  ...span,
                  events: [
                    {
                      name: "polyweb.provider.response",
                      timestamp: "2026-09-29T09:10:02.045000Z",
                      attributes: {
                        result_count: 2,
                        results: [
                          { title: "No URL here" },
                          {
                            title: "Has URL",
                            url: "https://example.com/a",
                            source: "keenable",
                            score: 0.5,
                          },
                        ],
                      },
                    },
                  ],
                }
              : span
        ),
      })
    )
    const firstAttempt = hostile.stages.find(
      (stage) => stage.name === "polyweb.provider"
    )!
    const decoded = firstAttempt.events.find(
      (event) => event.name === "polyweb.provider.response"
    )!
    expect(decoded.attributes.results).toHaveLength(2)
  })

  it("drops events with unusable name or timestamp while keeping valid ones", () => {
    const detail = mapTraceDetail(
      traceDetailFixture({
        spans: [
          {
            span_id: "aabbccddeeff0011",
            parent_span_id: null,
            name: "POST /search",
            stage: "Search request",
            kind: "server",
            started_at: "2026-09-29T09:15:00.000000Z",
            duration_ms: 10,
            outcome: "success",
            error: null,
            events: [
              { name: "good", timestamp: "2026-09-29T09:15:00.001000Z", attributes: { a: 1 } },
              { name: null, timestamp: "2026-09-29T09:15:00.001000Z", attributes: {} },
              { name: "bad-time", timestamp: "yesterday", attributes: {} },
              "not-an-event",
            ],
          },
        ],
      })
    )

    expect(detail.stages[0]?.events.map((event) => event.name)).toEqual(["good"])
    expect(detail.stages[0]?.events[0]?.attributes).toEqual({ a: 1 })
  })

  it("decodes non-record attributes objects to an empty record", () => {
    const detail = mapTraceDetail(
      traceDetailFixture({
        spans: [
          {
            span_id: "aabbccddeeff0011",
            parent_span_id: null,
            name: "POST /search",
            stage: "Search request",
            kind: "server",
            started_at: "2026-09-29T09:15:00.000000Z",
            duration_ms: 10,
            outcome: "success",
            error: null,
            events: [
              {
                name: "weird",
                timestamp: "2026-09-29T09:15:00.001000Z",
                attributes: "flattened",
              },
            ],
          },
        ],
      })
    )

    expect(detail.stages[0]?.events[0]?.attributes).toEqual({})
  })
})

describe("decodeSearchResults", () => {
  it("decodes shared result lists with original order preserved", async () => {
    const { decodeSearchResults } = await import("./mappers")
    const results = decodeSearchResults([
      { title: "B", url: "https://example.com/b", source: "tavily", score: 0.5 },
      { title: "A", url: "https://example.com/a", source: "keenable", score: 0.9 },
    ])

    expect(results.map((result) => result.url)).toEqual([
      "https://example.com/b",
      "https://example.com/a",
    ])
  })

  it("returns an empty list for non-array payloads", async () => {
    const { decodeSearchResults } = await import("./mappers")

    expect(decodeSearchResults(null)).toEqual([])
    expect(decodeSearchResults("results")).toEqual([])
    expect(decodeSearchResults({})).toEqual([])
  })

  it("coerces non-numeric scores to null instead of fabricating them", async () => {
    const { decodeSearchResults } = await import("./mappers")
    const [result] = decodeSearchResults([
      { title: "A", url: "https://example.com/a", score: "0.9" },
    ])

    expect(result?.score).toBeNull()
  })
})

/**
 * The wire `spans[*].provider` field is the source of truth for provider
 * identity (PLAN §6.3 item 2): `mapStages` decodes `record.provider` with
 * `asString` (malformed/non-string → null) into `TraceStage.providerId`.
 */
describe("mapTraceDetail span provider identity", () => {
  function stageById(detail: { stages: Array<Record<string, unknown>> }, spanId: string) {
    const stage = detail.stages.find((candidate) => candidate.spanId === spanId)
    if (stage === undefined) throw new Error(`missing stage ${spanId}`)
    return stage
  }

  it("decodes the span-level provider field to TraceStage.providerId", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture()) as unknown as {
      stages: Array<Record<string, unknown>>
    }

    expect(stageById(detail, "a100000000000003")).toMatchObject({ providerId: "keenable" })
    expect(stageById(detail, "a100000000000006")).toMatchObject({ providerId: "tavily" })
  })

  it("exposes all seven deterministic fanout identities in wire order", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture()) as unknown as {
      stages: Array<Record<string, unknown>>
    }
    const providerStages = detail.stages.filter(
      (stage) => stage.name === "polyweb.provider"
    )

    expect(providerStages).toHaveLength(7)
    expect(providerStages.map((stage) => stage.providerId)).toEqual([
      "keenable",
      "tavily",
      "brave",
      "exa",
      "firecrawl",
      "youcom",
      "parallel",
    ])
  })

  it("preserves provider on the failed/empty attempt that carries no results", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture()) as unknown as {
      stages: Array<Record<string, unknown>>
    }

    expect(stageById(detail, "f100000000000001")).toMatchObject({
      providerId: "parallel",
      outcome: "error",
    })
    expect(stageById(detail, "c100000000000001")).toMatchObject({ providerId: "exa" })
  })

  it("keeps providerId null when the span carries no provider (nullable legacy)", () => {
    const detail = mapTraceDetail(
      traceDetailFixture({
        spans: [
          {
            span_id: "aabbccddeeff0011",
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
        ],
      })
    ) as unknown as { stages: Array<Record<string, unknown>> }

    expect(detail.stages[0]?.providerId).toBeNull()
  })

  it("rejects malformed provider values to null instead of leaking them", () => {
    for (const provider of [42, {}, [], true]) {
      const detail = mapTraceDetail(
        traceDetailFixture({
          spans: [
            {
              span_id: "aabbccddeeff0011",
              parent_span_id: null,
              name: "polyweb.provider",
              stage: "Provider request",
              kind: "client",
              provider,
              started_at: "2026-09-29T09:15:00.000000Z",
              duration_ms: 10,
              outcome: "success",
              error: null,
              events: [],
            },
          ],
        })
      ) as unknown as { stages: Array<Record<string, unknown>> }

      expect(detail.stages[0]?.providerId).toBeNull()
    }
  })
})

/**
 * TASK-000063 activity identity: backend snake_case
 * (`user_id`, `actor_type`, `actor_id`, `username`, `first_name`,
 * `last_name`, `email`) decodes into the optional actor
 * (`kind`/`displayName`/`email`).
 * Human rows resolve full name → username; API-key rows stay
 * key-identified even with stray profile values; legacy rows without actor
 * payload stay quiet with a null actor.
 */
describe("mapTraceSummary actor identity", () => {
  it("decodes a human actor with full name, ids, and contact fields", () => {
    const actor = mapTraceSummary(
      traceSummaryFixture({
        actor_type: "human",
        actor_id: "actor-123",
        user_id: "user-456",
        username: "jdoe",
        first_name: "Jane",
        last_name: "Doe",
        email: "jane@example.com",
      })
    )?.actor

    expect(actor).toEqual({
      kind: "human",
      displayName: "Jane Doe",
      email: "jane@example.com",
    })
  })

  it("resolves partial personal names without inventing missing parts", () => {
    expect(
      mapTraceSummary(
        traceSummaryFixture({ actor_type: "human", first_name: "Jane" })
      )?.actor.displayName
    ).toBe("Jane")
    expect(
      mapTraceSummary(traceSummaryFixture({ actor_type: "human", last_name: "Doe" }))
        ?.actor.displayName
    ).toBe("Doe")
  })

  it("falls back to username when no personal name is recorded", () => {
    const actor = mapTraceSummary(
      traceSummaryFixture({
        actor_type: "human",
        username: "jdoe",
        email: "jane@example.com",
      })
    )?.actor

    expect(actor).toMatchObject({
      kind: "human",
      displayName: "jdoe",
      email: "jane@example.com",
    })
  })

  it("keeps email-only humans with a null display name instead of coercing one", () => {
    const actor = mapTraceSummary(
      traceSummaryFixture({ actor_type: "human", email: "jane@example.com" })
    )?.actor

    expect(actor).toMatchObject({
      kind: "human",
      displayName: null,
      email: "jane@example.com",
    })
  })

  it("trims blank name parts and treats whitespace-only names as missing", () => {
    expect(
      mapTraceSummary(
        traceSummaryFixture({
          actor_type: "human",
          first_name: "  Jane  ",
          last_name: "   ",
          username: "jdoe",
        })
      )?.actor.displayName
    ).toBe("Jane")
    expect(
      mapTraceSummary(
        traceSummaryFixture({
          actor_type: "human",
          first_name: "   ",
          last_name: "  ",
          username: "   ",
        })
      )?.actor.displayName
    ).toBeNull()
  })

  it("keeps API-key rows key-identified even with stray human profile values", () => {
    const actor = mapTraceSummary(
      traceSummaryFixture({
        actor_type: "project_api_key",
        actor_id: "key-123",
        user_id: "user-456",
        username: "jdoe",
        first_name: "Jane",
        last_name: "Doe",
        email: "jane@example.com",
      })
    )?.actor

    expect(actor).toEqual({
      kind: "project_api_key",
      displayName: null,
      email: null,
    })
  })

  it("keeps legacy rows without actor payload quiet with a null actor", () => {
    const summary = mapTraceSummary(traceSummaryFixture())

    expect(summary?.traceId).toBe(SUCCESS_TRACE_ID)
    expect(summary?.actor).toEqual({
      kind: null,
      displayName: null,
      email: null,
    })
  })

  it("drops unknown actor types to null kind without failing the row", () => {
    const summary = mapTraceSummary(
      traceSummaryFixture({ actor_type: "service_account", first_name: "Jane" })
    )

    expect(summary?.traceId).toBe(SUCCESS_TRACE_ID)
    expect(summary?.actor.kind).toBeNull()
  })

  it("drops wrong-typed actor fields to null without failing the row", () => {
    const summary = mapTraceSummary(
      traceSummaryFixture({
        actor_type: 42,
        actor_id: 123,
        user_id: {},
        username: 42,
        first_name: 42,
        last_name: [],
        email: 42,
      })
    )

    expect(summary?.traceId).toBe(SUCCESS_TRACE_ID)
    expect(summary?.actor).toEqual({
      kind: null,
      displayName: null,
      email: null,
    })
  })

  it("carries the decoded actor through mapTraceDetail", () => {
    const detail = mapTraceDetail(
      traceDetailFixture({
        actor_type: "human",
        actor_id: "actor-123",
        user_id: "user-456",
        username: "jdoe",
        first_name: "Jane",
        last_name: "Doe",
        email: "jane@example.com",
      })
    )

    expect(detail.traceId).toBe(SUCCESS_TRACE_ID)
    expect(detail.actor).toEqual({
      kind: "human",
      displayName: "Jane Doe",
      email: "jane@example.com",
    })
  })
})
