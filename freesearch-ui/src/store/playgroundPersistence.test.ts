import { describe, it, expect, afterEach, vi } from "vitest"
import type { FetchResponse, SearchResponse } from "@/domains/execution"
import {
  INTERRUPTED_REQUEST_ERROR,
  MAX_PERSISTED_PLAYGROUND_BYTES,
  LEGACY_PLAYGROUND_PERSIST_KEY,
  PLAYGROUND_PERSIST_KEY,
  PLAYGROUND_PERSIST_VERSION,
  createPlaygroundPersistConfig,
  discardLegacyPlaygroundSnapshot,
  createPlaygroundStorage,
  playgroundPersistKey,
  sanitizePersistedPlayground,
} from "./playgroundPersistence"
import { ADMIN_ACCOUNT_ID, AGENT_ACCOUNT_ID } from "@/test/authFixtures"
import { PROJECT_ALPHA_ID, PROJECT_BETA_ID } from "@/test/accessFixtures"
import { initialPlaygroundState } from "./playgroundSlice"
import type { PlaygroundState } from "./playgroundSlice"

function searchResponse(): SearchResponse {
  return {
    query: "persisted query",
    results: [
      {
        id: "brave-0",
        providerId: "brave",
        providerName: "Brave",
        title: "Persisted result",
        url: "https://example.com/persisted",
        snippet: "Persisted snippet.",
        relevanceScore: 0.92,
      },
    ],
    totalResults: 1,
    selectedProviderId: "brave",
    fallbackChain: ["brave"],
    waterfall: [
      {
        providerId: "brave",
        providerName: "Brave",
        latencyMs: 187,
        status: "success",
        resultsCount: 1,
        costCredits: 1,
      },
    ],
    executionTimeMs: 187,
    costEstimateCredits: 1,
    timestamp: "2026-09-06T10:02:00.000Z",
  }
}

function fetchResponse(): FetchResponse {
  return {
    document: {
      url: "https://example.com/doc",
      title: "Persisted document",
      content: "# Persisted\n\nBody.",
      markdown: "# Persisted\n\nBody.",
      providerId: "keenable",
      providerName: "Keenable",
      statusCode: null,
      contentLength: 18,
      executionTimeMs: 412,
    },
    providerId: "keenable",
    fallbackChain: ["keenable"],
    costEstimateCredits: 2,
    executionTimeMs: 412,
    timestamp: "2026-09-06T10:03:01.000Z",
  }
}

/** Mirrors the persistoid envelope: every field value serialized on its own. */
function encodeEnvelope(fields: Record<string, unknown>): string {
  const encoded: Record<string, string> = {}
  for (const [field, value] of Object.entries(fields)) {
    encoded[field] = JSON.stringify(value)
  }
  return JSON.stringify(encoded)
}

function decodeEnvelope(raw: string): Record<string, unknown> {
  const envelope = JSON.parse(raw) as Record<string, string>
  const fields: Record<string, unknown> = {}
  for (const [field, value] of Object.entries(envelope)) {
    fields[field] = JSON.parse(value) as unknown
  }
  return fields
}

function versioned(state: Partial<PlaygroundState> & Record<string, unknown>): string {
  return encodeEnvelope({
    ...initialPlaygroundState,
    ...state,
    _persist: { version: PLAYGROUND_PERSIST_VERSION, rehydrated: false },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe("playgroundPersistence identity", () => {
  it("uses the exact project key, empty prefix, and version 2", () => {
    expect(PLAYGROUND_PERSIST_KEY).toBe("freesearch:playground:v2")
    expect(PLAYGROUND_PERSIST_VERSION).toBe(2)
    const config = createPlaygroundPersistConfig(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    expect(config.key).toBe(`freesearch:playground:v2:${ADMIN_ACCOUNT_ID}:${PROJECT_ALPHA_ID}`)
    expect(config.key).toBe(playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID))
    expect(config.keyPrefix).toBe("")
    expect(config.version).toBe(2)
  })

  it("caps persisted snapshots at 2 MiB and names the interrupted-request error", () => {
    expect(MAX_PERSISTED_PLAYGROUND_BYTES).toBe(2 * 1024 * 1024)
    expect(INTERRUPTED_REQUEST_ERROR).toBe("Previous request was interrupted by reload.")
  })

  it("produces different keys for different accounts and different projects", () => {
    const adminKey = playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const agentKey = playgroundPersistKey(AGENT_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const betaKey = playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_BETA_ID)
    expect(new Set([adminKey, agentKey, betaKey]).size).toBe(3)
    expect(createPlaygroundPersistConfig(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID).key).toBe(adminKey)
    expect(createPlaygroundPersistConfig(AGENT_ACCOUNT_ID, PROJECT_ALPHA_ID).key).toBe(agentKey)
    expect(createPlaygroundPersistConfig(ADMIN_ACCOUNT_ID, PROJECT_BETA_ID).key).toBe(betaKey)
  })

  it("discards every legacy v1 snapshot (unowned and account keys) while keeping project snapshots", () => {
    const projectKey = playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const legacyAccountKey = `${LEGACY_PLAYGROUND_PERSIST_KEY}:${ADMIN_ACCOUNT_ID}`
    window.localStorage.setItem(LEGACY_PLAYGROUND_PERSIST_KEY, '{"stale":true}')
    window.localStorage.setItem(legacyAccountKey, '{"stale":true}')
    window.localStorage.setItem(projectKey, '{"kept":true}')
    createPlaygroundPersistConfig(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    // The config itself never writes storage; the provider's mount effect discards.
    expect(window.localStorage.getItem(LEGACY_PLAYGROUND_PERSIST_KEY)).toBe('{"stale":true}')
    discardLegacyPlaygroundSnapshot()
    expect(window.localStorage.getItem(LEGACY_PLAYGROUND_PERSIST_KEY)).toBeNull()
    expect(window.localStorage.getItem(legacyAccountKey)).toBeNull()
    expect(window.localStorage.getItem(projectKey)).toBe('{"kept":true}')
  })

  it("never migrates the legacy account key into a project config", async () => {
    const storage = createPlaygroundStorage()
    const legacyAccountKey = `${LEGACY_PLAYGROUND_PERSIST_KEY}:${ADMIN_ACCOUNT_ID}`
    await storage.setItem(legacyAccountKey, versioned({ query: "legacy query" }))
    const projectKey = playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    await expect(storage.getItem(projectKey)).resolves.toBeNull()
  })
})

describe("playgroundPersistence round-trip", () => {
  it("writes and reads back drafts, options, full responses, and errors", async () => {
    const storage = createPlaygroundStorage()
    const state: PlaygroundState = {
      ...initialPlaygroundState,
      mode: "fetch",
      query: "round-trip query",
      fetchUrl: "https://example.com/round-trip",
      selectedProviderId: "brave",
      resultCount: 25,
      activeSearch: searchResponse(),
      activeFetch: fetchResponse(),
      searchStatus: "succeeded",
      fetchStatus: "failed",
      searchError: null,
      fetchError: "fetch boom",
    }
    await storage.setItem(PLAYGROUND_PERSIST_KEY, versioned({ ...state }))
    expect(window.localStorage.getItem(PLAYGROUND_PERSIST_KEY)).not.toBeNull()

    const raw = await storage.getItem(PLAYGROUND_PERSIST_KEY)
    expect(raw).not.toBeNull()
    const fields = decodeEnvelope(raw as string)
    expect(fields.mode).toBe("fetch")
    expect(fields.query).toBe("round-trip query")
    expect(fields.fetchUrl).toBe("https://example.com/round-trip")
    expect(fields.selectedProviderId).toBe("brave")
    expect(fields.resultCount).toBe(25)
    expect(fields.activeSearch).toEqual(searchResponse())
    expect(fields.activeFetch).toEqual(fetchResponse())
    expect(fields.searchStatus).toBe("succeeded")
    expect(fields.fetchStatus).toBe("failed")
    expect(fields.searchError).toBeNull()
    expect(fields.fetchError).toBe("fetch boom")
  })

  it("returns null when nothing was stored", async () => {
    await expect(createPlaygroundStorage().getItem(PLAYGROUND_PERSIST_KEY)).resolves.toBeNull()
  })
})

describe("sanitizePersistedPlayground untrusted input", () => {
  it("resets absent, malformed, and unsupported-version payloads to the initial state", () => {
    expect(sanitizePersistedPlayground(null)).toEqual(initialPlaygroundState)
    expect(sanitizePersistedPlayground(undefined)).toEqual(initialPlaygroundState)
    expect(sanitizePersistedPlayground("nope")).toEqual(initialPlaygroundState)
    expect(sanitizePersistedPlayground([])).toEqual(initialPlaygroundState)
    expect(sanitizePersistedPlayground({ query: "x" })).toEqual(initialPlaygroundState)
    expect(
      sanitizePersistedPlayground({ ...initialPlaygroundState, _persist: { version: 1 } })
    ).toEqual(initialPlaygroundState)
    expect(
      sanitizePersistedPlayground({ ...initialPlaygroundState, _persist: { rehydrated: true } })
    ).toEqual(initialPlaygroundState)
  })

  it("keeps recognized fields while falling back for unknown values", () => {
    const sanitized = sanitizePersistedPlayground({
      ...initialPlaygroundState,
      _persist: { version: PLAYGROUND_PERSIST_VERSION, rehydrated: true },
      mode: "copilot",
      query: 42,
      fetchUrl: null,
      selectedProviderId: "brave",
      resultCount: 500,
      activeSearch: { results: [] },
      activeFetch: { document: {} },
      searchStatus: "exploding",
      fetchStatus: "succeeded",
      fetchError: 7,
    })
    expect(sanitized.mode).toBe("search")
    expect(sanitized.query).toBe("")
    expect(sanitized.fetchUrl).toBe("")
    expect(sanitized.selectedProviderId).toBe("brave")
    expect(sanitized.resultCount).toBe(100)
    expect(sanitized.activeSearch).toBeNull()
    expect(sanitized.activeFetch).toBeNull()
    expect(sanitized.searchStatus).toBe("idle")
    expect(sanitized.searchError).toBeNull()
    expect(sanitized.fetchStatus).toBe("succeeded")
    expect(sanitized.fetchError).toBeNull()
  })

  it("clamps malformed persisted result counts through the shared 1..100 contract", () => {
    const base = { ...initialPlaygroundState, _persist: { version: PLAYGROUND_PERSIST_VERSION } }
    expect(sanitizePersistedPlayground({ ...base, resultCount: 0 }).resultCount).toBe(1)
    expect(sanitizePersistedPlayground({ ...base, resultCount: "25" }).resultCount).toBe(6)
    expect(sanitizePersistedPlayground({ ...base, resultCount: NaN }).resultCount).toBe(1)
  })
})

describe("playgroundPersistence interrupted loading", () => {
  it("converts orphaned loading to an interrupted failure while keeping results, without any network call", async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal("fetch", fetchSpy)
    const storage = createPlaygroundStorage()
    await storage.setItem(
      PLAYGROUND_PERSIST_KEY,
      versioned({
        query: "interrupted query",
        activeSearch: searchResponse(),
        searchStatus: "loading",
        searchError: null,
        fetchStatus: "loading",
        fetchError: null,
      })
    )

    const raw = await storage.getItem(PLAYGROUND_PERSIST_KEY)
    expect(raw).not.toBeNull()
    const fields = decodeEnvelope(raw as string)
    expect(fields.query).toBe("interrupted query")
    expect(fields.activeSearch).toEqual(searchResponse())
    expect(fields.searchStatus).toBe("failed")
    expect(fields.searchError).toBe(INTERRUPTED_REQUEST_ERROR)
    expect(fields.fetchStatus).toBe("failed")
    expect(fields.fetchError).toBe(INTERRUPTED_REQUEST_ERROR)
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it("keeps a persisted failure's own error text instead of the interrupted message", async () => {
    const storage = createPlaygroundStorage()
    await storage.setItem(
      PLAYGROUND_PERSIST_KEY,
      versioned({ searchStatus: "failed", searchError: "stubbed provider unavailable" })
    )
    const fields = decodeEnvelope((await storage.getItem(PLAYGROUND_PERSIST_KEY)) as string)
    expect(fields.searchStatus).toBe("failed")
    expect(fields.searchError).toBe("stubbed provider unavailable")
  })

  it("returns null for a hand-edited non-JSON payload instead of trusting it", async () => {
    window.localStorage.setItem(PLAYGROUND_PERSIST_KEY, "definitely not json{{{")
    await expect(createPlaygroundStorage().getItem(PLAYGROUND_PERSIST_KEY)).resolves.toBeNull()
  })

  it("resets an unsupported version to the initial state on read", async () => {
    const storage = createPlaygroundStorage()
    await storage.setItem(
      PLAYGROUND_PERSIST_KEY,
      encodeEnvelope({ query: "stale", _persist: { version: 99, rehydrated: true } })
    )
    const fields = decodeEnvelope((await storage.getItem(PLAYGROUND_PERSIST_KEY)) as string)
    expect(fields.query).toBe("")
    expect(fields.searchStatus).toBe("idle")
  })
})

describe("playgroundPersistence bounded writes", () => {
  it("writes payloads at and below the 2 MiB cap without warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    const storage = createPlaygroundStorage()
    const below = "q".repeat(MAX_PERSISTED_PLAYGROUND_BYTES - 8)
    await storage.setItem(PLAYGROUND_PERSIST_KEY, below)
    expect(window.localStorage.getItem(PLAYGROUND_PERSIST_KEY)).toBe(below)

    const atCap = "q".repeat(MAX_PERSISTED_PLAYGROUND_BYTES)
    await storage.setItem(PLAYGROUND_PERSIST_KEY, atCap)
    expect(window.localStorage.getItem(PLAYGROUND_PERSIST_KEY)).toBe(atCap)
    expect(warn).not.toHaveBeenCalled()
  })

  it("measures UTF-8 bytes so multibyte text trips the cap by size, not length", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    const storage = createPlaygroundStorage()
    // "é" is 2 bytes in UTF-8: half the char count of the cap still overflows.
    const multibyteOver = "é".repeat(Math.ceil(MAX_PERSISTED_PLAYGROUND_BYTES / 2) + 1)
    expect(multibyteOver.length).toBeLessThan(MAX_PERSISTED_PLAYGROUND_BYTES)
    await storage.setItem(PLAYGROUND_PERSIST_KEY, multibyteOver)
    expect(window.localStorage.getItem(PLAYGROUND_PERSIST_KEY)).toBeNull()
    expect(warn).toHaveBeenCalledTimes(1)

    const multibyteUnder = "é".repeat(100)
    await storage.setItem(PLAYGROUND_PERSIST_KEY, multibyteUnder)
    expect(window.localStorage.getItem(PLAYGROUND_PERSIST_KEY)).toBe(multibyteUnder)
  })

  it("drops oversized snapshots with one warning instead of throwing", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    const storage = createPlaygroundStorage()
    window.localStorage.setItem(PLAYGROUND_PERSIST_KEY, versioned({ query: "stale" }))
    await storage.setItem(PLAYGROUND_PERSIST_KEY, "q".repeat(MAX_PERSISTED_PLAYGROUND_BYTES + 1))
    expect(window.localStorage.getItem(PLAYGROUND_PERSIST_KEY)).toBeNull()
    expect(warn).toHaveBeenCalledTimes(1)
    expect(String(warn.mock.calls[0]?.[0] ?? "")).toMatch(/was not persisted/)
  })

  it("clears stale storage and warns without throwing on quota rejection", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    window.localStorage.setItem(PLAYGROUND_PERSIST_KEY, versioned({ query: "stale" }))
    const quotaError = Object.assign(new Error("quota"), { name: "QuotaExceededError" })
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementationOnce(() => {
      throw quotaError
    })
    const removeItem = vi.spyOn(Storage.prototype, "removeItem")

    await expect(
      createPlaygroundStorage().setItem(PLAYGROUND_PERSIST_KEY, versioned({ query: "fresh" }))
    ).resolves.toBeUndefined()
    expect(setItem).toHaveBeenCalledTimes(1)
    expect(removeItem).toHaveBeenCalledWith(PLAYGROUND_PERSIST_KEY)
    expect(warn).toHaveBeenCalledTimes(1)
    expect(String(warn.mock.calls[0]?.[0] ?? "")).toMatch(/QuotaExceededError/)
  })

  it("clears stale storage and warns without throwing on security rejection", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    vi.spyOn(Storage.prototype, "setItem").mockImplementationOnce(() => {
      throw Object.assign(new Error("denied"), { name: "SecurityError" })
    })
    await expect(
      createPlaygroundStorage().setItem(PLAYGROUND_PERSIST_KEY, versioned({ query: "fresh" }))
    ).resolves.toBeUndefined()
    expect(window.localStorage.getItem(PLAYGROUND_PERSIST_KEY)).toBeNull()
    expect(warn).toHaveBeenCalledTimes(1)
    expect(String(warn.mock.calls[0]?.[0] ?? "")).toMatch(/SecurityError/)
  })

  it("removeItem resolves without throwing", async () => {
    const storage = createPlaygroundStorage()
    await storage.setItem(PLAYGROUND_PERSIST_KEY, versioned({ query: "x" }))
    await expect(storage.removeItem(PLAYGROUND_PERSIST_KEY)).resolves.toBeUndefined()
    expect(window.localStorage.getItem(PLAYGROUND_PERSIST_KEY)).toBeNull()
  })

  it("resolves null when reading storage throws (blocked origin)", async () => {
    const storage = createPlaygroundStorage()
    vi.spyOn(Storage.prototype, "getItem").mockImplementationOnce(() => {
      throw Object.assign(new Error("denied"), { name: "SecurityError" })
    })
    await expect(storage.getItem(PLAYGROUND_PERSIST_KEY)).resolves.toBeNull()
  })

  it("resolves null when localStorage is absent", async () => {
    vi.stubGlobal("localStorage", null)
    await expect(createPlaygroundStorage().getItem(PLAYGROUND_PERSIST_KEY)).resolves.toBeNull()
  })

  it("stays throw-free when accessing localStorage itself throws", async () => {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage")
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get() {
        throw Object.assign(new Error("denied"), { name: "SecurityError" })
      },
    })
    try {
      const storage = createPlaygroundStorage()
      await expect(storage.getItem(PLAYGROUND_PERSIST_KEY)).resolves.toBeNull()
      await expect(
        storage.setItem(PLAYGROUND_PERSIST_KEY, versioned({ query: "x" }))
      ).resolves.toBeUndefined()
      await expect(storage.removeItem(PLAYGROUND_PERSIST_KEY)).resolves.toBeUndefined()
    } finally {
      if (descriptor) Object.defineProperty(globalThis, "localStorage", descriptor)
    }
  })
})
