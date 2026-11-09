/**
 * Execution slice — verbatim extract from ../backendFixtures.ts (step 1).
 */

export function searchResponseFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    query: "live backend query",
    results: [
      {
        title: "Live backend result one",
        url: "https://example.com/one",
        snippet: "First live snippet.",
        published_at: "2026-09-05T14:30:00Z",
        source: "Example Source",
        score: 0.92,
        metadata: {},
      },
      {
        title: "Live backend result two",
        url: "https://example.com/two",
        snippet: "Second live snippet.",
        published_at: null,
        source: null,
        score: null,
        metadata: {},
      },
    ],
    provider: "tavily",
    total_results: 2,
    usage: {
      provider: "tavily",
      operation: "search",
      units: "1",
      observed_at: "2026-09-06T10:02:00Z",
      request_id: "req-123",
      metadata: {},
      latency_ms: 187,
      status: "success",
    },
    ...overrides,
  }
}

export function minimalSearchResponseFixture(): Record<string, unknown> {
  return {
    query: "minimal query",
    results: [],
    provider: "you",
    total_results: null,
    usage: null,
  }
}

export function fetchResponseFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    provider: "firecrawl",
    document: {
      url: "https://example.com/doc",
      content: "# Live document\n\nFetched markdown body.",
      title: "Live document title",
      content_type: "text/markdown",
      fetched_at: "2026-09-06T10:03:00Z",
      metadata: {},
    },
    usage: {
      provider: "firecrawl",
      operation: "fetch",
      units: "2",
      observed_at: "2026-09-06T10:03:01Z",
      request_id: null,
      metadata: {},
      latency_ms: 412,
      status: "success",
    },
    ...overrides,
  }
}
