import React, { useState } from "react"
import {
  Search,
  FileText,
  ExternalLink,
} from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { Button } from "@/components/ui/button"
import type { SearchResult } from "@/types/freesearch"

function isEligibleForOperation(
  provider: ReturnType<typeof useFreeSearch>["providers"][number],
  operation: "search" | "fetch"
): boolean {
  if (!provider.globalEnabled) return false
  return operation === "search"
    ? provider.searchEnabled && provider.capabilities.includes("search")
    : provider.fetchEnabled && provider.capabilities.includes("fetch")
}

export const SearchPlayground: React.FC = () => {
  const {
    providers,
    fallbackConfig,
    activeSearch,
    activeFetch,
    isSearching,
    isFetching,
    searchError,
    fetchError,
    runSearch,
    runFetch,
  } = useFreeSearch()

  const [mode, setMode] = useState<"search" | "fetch">("search")
  const [query, setQuery] = useState("")
  const [fetchUrl, setFetchUrl] = useState("")
  const [selectedProviderId, setSelectedProviderId] = useState<string>("auto")
  const [searchDepth, setSearchDepth] = useState<"fast" | "balanced" | "deep">("balanced")
  const [selectedResultForPreview, setSelectedResultForPreview] = useState<SearchResult | null>(null)
  const [showJsonInspector, setShowJsonInspector] = useState(false)
  const [copied, setCopied] = useState(false)

  const eligibleProviders = providers.filter((provider) =>
    isEligibleForOperation(provider, mode)
  )

  const handleExecute = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()

    const selectedProvider =
      selectedProviderId !== "auto" &&
      eligibleProviders.some((provider) => provider.id === selectedProviderId)
        ? selectedProviderId
        : undefined

    if (mode === "search") {
      if (!query.trim()) return
      const res = await runSearch({
        query: query.trim(),
        providerIds: selectedProvider ? [selectedProvider] : undefined,
        mode: searchDepth,
        maxResults: 6,
        timeoutMs: 3000,
      })
      setSelectedResultForPreview(res?.results[0] ?? null)
    } else {
      if (!fetchUrl.trim()) return
      await runFetch({
        url: fetchUrl.trim(),
        providerId: selectedProvider,
        format: "markdown",
        timeoutMs: 4000,
      })
      setSelectedResultForPreview(null)
    }
  }

  const switchMode = (next: "search" | "fetch") => {
    if (
      selectedProviderId !== "auto" &&
      !providers.some((provider) =>
        provider.id === selectedProviderId && isEligibleForOperation(provider, next)
      )
    ) {
      setSelectedProviderId("auto")
    }
    setMode(next)
    setSelectedResultForPreview(null)
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const quickQueries = [
    "python async search aggregator",
    "circuit breaker resilience patterns",
    "keenable keyless free tier",
    "react server components streaming",
  ]

  return (
    <div className="space-y-8">
      {/* Page heading + mode toggle */}
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-4 pb-2 border-b border-[var(--border-subtle)]">
        <div>
          <h2 className="text-[var(--text-strong)]">Search Playground</h2>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Run queries and fetches across the provider fleet with live arbitration.
          </p>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={() => switchMode("search")}
              aria-label="Search mode"
              aria-pressed={mode === "search"}
              className="text-[13px] font-medium pb-1 transition-colors"
              style={{
                color: mode === "search" ? "var(--text-strong)" : "var(--muted)",
                borderBottom: mode === "search" ? "2px solid var(--signal)" : "2px solid transparent",
              }}
            >
              Search
            </button>
            <button
              type="button"
              onClick={() => switchMode("fetch")}
              aria-pressed={mode === "fetch"}
              className="text-[13px] font-medium pb-1 transition-colors"
              style={{
                color: mode === "fetch" ? "var(--text-strong)" : "var(--muted)",
                borderBottom: mode === "fetch" ? "2px solid var(--signal)" : "2px solid transparent",
              }}
            >
              Fetch
            </button>
          </div>

          <div className="flex items-center gap-4 text-[13px] text-[var(--muted)]">
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block w-1.5 h-1.5 rounded-full"
                style={{ background: "var(--status-healthy)" }}
              />
              <span className="tnum">{eligibleProviders.length} providers</span>
            </span>
            <span>
              Fallback {fallbackConfig.enabled ? "active" : "disabled"}
            </span>
          </div>
        </div>
      </div>

      {/* Search input — Hero element */}
      <form onSubmit={handleExecute}>
        <div className="relative">
          <div
            className="absolute left-0 top-1/2 -translate-y-1/2 pl-1"
            style={{ color: "var(--muted)" }}
          >
            {mode === "search" ? <Search className="size-5" /> : <FileText className="size-5" />}
          </div>
          <input
            type={mode === "search" ? "text" : "url"}
            value={mode === "search" ? query : fetchUrl}
            onChange={(e) =>
              mode === "search" ? setQuery(e.target.value) : setFetchUrl(e.target.value)
            }
            placeholder={
              mode === "search"
                ? "Search across all providers..."
                : "Enter a URL to fetch and convert..."
            }
            className="w-full bg-transparent py-3 pl-9 pr-28 text-[15px] font-mono outline-none placeholder:text-[var(--muted)]"
            style={{
              color: "var(--text-strong)",
              borderBottom: "1px solid var(--border-subtle)",
            }}
          />
          <div className="absolute right-0 top-1/2 -translate-y-1/2">
            <Button
              type="submit"
              disabled={isSearching || isFetching}
              className="rounded-md px-4 py-1.5 text-[13px] font-medium text-white"
              style={{ background: "var(--signal)" }}
            >
              {isSearching || isFetching ? "Executing..." : mode === "search" ? "Search" : "Fetch"}
            </Button>
          </div>
        </div>

        {/* Quick queries */}
        {mode === "search" && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-[13px] text-[var(--muted)]">
            <span className="text-[var(--muted)]">Suggestions:</span>
            {quickQueries.map((q, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => setQuery(q)}
                className="hover:underline transition-colors hover:text-[var(--text-strong)]"
              >
                {q}
              </button>
            ))}
          </div>
        )}

        {/* Controls row */}
        <div className="flex flex-wrap items-center gap-4 mt-3 text-[13px] text-[var(--muted)]">
          <div className="flex items-center gap-2">
            <span>Provider:</span>
            <select
              value={selectedProviderId}
              onChange={(e) => setSelectedProviderId(e.target.value)}
              className="rounded px-2.5 py-1 text-[13px] outline-none bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)]"
            >
              <option value="auto">Auto arbitration</option>
              {eligibleProviders.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          {mode === "search" && (
            <div className="flex items-center gap-2">
              <span>Depth:</span>
              <div className="inline-flex rounded border border-[var(--border-subtle)] overflow-hidden">
                {(["fast", "balanced", "deep"] as const).map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setSearchDepth(d)}
                    aria-pressed={searchDepth === d}
                    className="px-2.5 py-1 text-[13px] capitalize transition-colors"
                    style={{
                      background: searchDepth === d ? "var(--signal-muted)" : "transparent",
                      color: searchDepth === d ? "var(--signal)" : "var(--muted)",
                    }}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </form>

      {/* Error display */}
      {(searchError || fetchError) && (
        <p className="text-[13px]" style={{ color: "var(--status-danger)" }}>
          {searchError || fetchError}
        </p>
      )}

      {/* Widescreen Results Layout: Results List + Inspector Pane */}
      {mode === "search" && activeSearch && (
        <div className="space-y-6 pt-2">
          {/* Telemetry bar */}
          <div className="flex flex-wrap items-center justify-between gap-4 text-[13px] py-2.5 px-3 rounded-lg bg-[var(--elevated)] border border-[var(--border-subtle)] text-[var(--muted)]">
            <div className="flex items-center gap-6 tnum">
              <span>
                Latency <span className="text-[var(--text-strong)]">{activeSearch.executionTimeMs}ms</span>
              </span>
              <span>
                Units <span className="text-[var(--text-strong)]">{activeSearch.costEstimateCredits}</span>
              </span>
              <span>
                Resolved by <span className="text-[var(--signal)] font-medium">{activeSearch.selectedProviderId}</span>
              </span>
              <span>
                Results <span className="text-[var(--text-strong)]">{activeSearch.results.length}</span>
              </span>
            </div>

            <button
              type="button"
              onClick={() => setShowJsonInspector(!showJsonInspector)}
              className="text-[13px] text-[var(--signal)] hover:underline"
            >
              {showJsonInspector ? "Hide raw JSON" : "Inspect raw JSON"}
            </button>
          </div>

          {/* JSON inspector toggle */}
          {showJsonInspector && (
            <div className="relative border border-[var(--border-subtle)] rounded-lg overflow-hidden">
              <button
                type="button"
                onClick={() => copyToClipboard(JSON.stringify(activeSearch, null, 2))}
                className="absolute top-3 right-3 text-[13px] text-[var(--signal)] hover:underline bg-[var(--surface)] px-2 py-1 rounded border border-[var(--border-subtle)]"
              >
                {copied ? "Copied" : "Copy JSON"}
              </button>
              <pre className="p-4 text-[13px] font-mono leading-relaxed max-h-72 overflow-auto bg-[var(--elevated)] text-[var(--text)]">
                {JSON.stringify(activeSearch, null, 2)}
              </pre>
            </div>
          )}

          {/* 2-Column Split: Results List (left) + Detail Inspector / Preview (right) */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            {/* Left Column: Results List */}
            <div className="lg:col-span-7 space-y-3">
              <div className="flex items-center justify-between text-[13px] text-[var(--muted)] pb-1">
                <span>Returned results ({activeSearch.results.length})</span>
                <span>Select item to inspect</span>
              </div>

              <div className="space-y-2">
                {activeSearch.results.map((res) => {
                  const isSelected = selectedResultForPreview?.id === res.id
                  return (
                    <div
                      key={res.id}
                      onClick={() => setSelectedResultForPreview(res)}
                      className={`p-3.5 rounded-lg border transition-all cursor-pointer ${
                        isSelected
                          ? "border-[var(--signal)] bg-[var(--signal-muted)]"
                          : "border-[var(--border-subtle)] bg-[var(--surface)] hover:bg-[var(--elevated)]"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                          <h4 className="text-[14px] font-medium text-[var(--text-strong)] hover:text-[var(--signal)] transition-colors">
                            {res.title}
                          </h4>

                          <p className="text-[12px] font-mono text-[var(--muted)] truncate">
                            {res.url}
                          </p>

                          <p className="text-[13px] text-[var(--text)] line-clamp-2 leading-relaxed mt-1">
                            {res.snippet}
                          </p>

                          <div className="flex items-center gap-3 text-[12px] text-[var(--muted)] pt-1">
                            <span className="text-[var(--text-strong)]">{res.providerName}</span>
                            <span className="tnum">
                              {Math.round(res.relevanceScore * 100)}% match
                            </span>
                            {res.publishedDate && (
                              <span className="tnum">{res.publishedDate}</span>
                            )}
                          </div>
                        </div>

                        <a
                          href={res.url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="p-1 text-[var(--muted)] hover:text-[var(--text-strong)] transition-colors shrink-0"
                          title="Open external link"
                        >
                          <ExternalLink className="size-3.5" />
                        </a>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Right Column: Live Result Inspector & Waterfall Telemetry */}
            <div className="lg:col-span-5 space-y-6">
              {selectedResultForPreview ? (
                <div className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-4">
                  <div className="flex items-start justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
                    <div className="min-w-0">
                      <span className="text-[12px] text-[var(--signal)] block mb-1">
                        Result Inspector
                      </span>
                      <h3 className="text-[16px] font-medium text-[var(--text-strong)] leading-snug">
                        Selected result
                      </h3>
                    </div>

                    <a
                      href={selectedResultForPreview.url}
                      target="_blank"
                      rel="noreferrer"
                      className="p-1.5 rounded text-[var(--muted)] hover:text-white bg-[var(--surface)] border border-[var(--border-subtle)] transition-colors shrink-0"
                      title="Open source"
                    >
                      <ExternalLink className="size-3.5" />
                    </a>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <span className="text-[12px] text-[var(--muted)] block mb-1">Target URL</span>
                      <div className="p-2 rounded bg-[var(--surface)] border border-[var(--border-subtle)] font-mono text-[12px] text-[var(--text)] break-all">
                        {selectedResultForPreview.url}
                      </div>
                    </div>

                    <div>
                      <span className="text-[12px] text-[var(--muted)] block mb-1">Snippet summary</span>
                      <p className="text-[13px] text-[var(--text)] leading-relaxed p-2.5 rounded bg-[var(--surface)] border border-[var(--border-subtle)]">
                        {selectedResultForPreview.snippet}
                      </p>
                    </div>

                    <div className="pt-2 border-t border-[var(--border-subtle)] flex items-center justify-between text-[12px] text-[var(--muted)] tnum">
                      <span>Attributed: {selectedResultForPreview.providerName}</span>
                      <span>Score: {Math.round(selectedResultForPreview.relevanceScore * 100)}%</span>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="p-6 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] text-center text-[13px] text-[var(--muted)]">
                  Select a search result from the list to inspect full metadata and snippet extraction.
                </div>
              )}

              {/* Waterfall Latency Diagnostics */}
              {activeSearch?.waterfall && activeSearch.waterfall.length > 0 && (
                <div className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-3">
                  <div className="flex items-center justify-between text-[13px]">
                    <span className="font-medium text-[var(--text-strong)]">Execution waterfall</span>
                    <span className="text-[12px] text-[var(--muted)]">Trace unavailable from backend</span>
                  </div>

                  <div className="space-y-2">
                    {activeSearch.waterfall.map((item) => {
                      const maxLat = Math.max(...activeSearch.waterfall.map((w) => w.latencyMs)) || 100
                      const widthPercent = Math.max(12, Math.round((item.latencyMs / maxLat) * 100))
                      return (
                        <div key={item.providerId} className="flex items-center gap-3 text-[13px]">
                          <span className="w-24 truncate font-medium text-[var(--text)]">
                            {item.providerName}
                          </span>
                          <div className="flex-1 rounded h-4 overflow-hidden bg-[var(--surface)] border border-[var(--border-subtle)]">
                            <div
                              className="h-full flex items-center pl-1.5 text-[12px] font-medium text-white tnum transition-all duration-500"
                              style={{
                                width: `${widthPercent}%`,
                                background: item.status === "success" ? "var(--signal)" : "var(--status-danger)",
                              }}
                            >
                              {item.latencyMs}ms
                            </div>
                          </div>
                          <span className="text-[12px] w-16 text-right text-[var(--muted)] tnum">
                            {item.status === "success" ? `${item.resultsCount} res` : item.status}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Fetch result — Widescreen 2-column layout */}
      {mode === "fetch" && activeFetch && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start pt-2">
          {/* Left Column: Metadata & Outline */}
          <div className="lg:col-span-4 p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-4">
            <div>
              <span className="text-[12px] text-[var(--signal)] block mb-1">
                Document Metadata
              </span>
              <h3 className="text-[16px] font-medium text-[var(--text-strong)] leading-snug">
                {activeFetch.document.title}
              </h3>
            </div>

            <div className="space-y-2.5 text-[13px] text-[var(--muted)]">
              <div>
                <span className="text-[12px] block mb-1">Source URL</span>
                <div className="p-2 rounded bg-[var(--surface)] border border-[var(--border-subtle)] font-mono text-[12px] text-[var(--text)] break-all">
                  {activeFetch.document.url}
                </div>
              </div>

              <div className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)]">
                <span>Provider</span>
                <span className="text-[var(--text)]">{activeFetch.document.providerName}</span>
              </div>

              <div className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)]">
                <span>Status code</span>
                <span className="tnum" style={{ color: "var(--status-healthy)" }} title="HTTP status not exposed by backend">
                  {activeFetch.document.statusCode ?? "—"}
                </span>
              </div>

              <div className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)]">
                <span>Content length</span>
                <span className="text-[var(--text)] tnum">
                  {new TextEncoder().encode(activeFetch.document.content).length} bytes
                </span>
              </div>

              <div className="flex items-center justify-between py-1.5">
                <span>Execution time</span>
                <span className="text-[var(--text)] tnum">{activeFetch.executionTimeMs}ms</span>
              </div>
            </div>
          </div>

          {/* Right Column: Markdown Document Content */}
          <div className="lg:col-span-8 p-5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-3">
            <div className="flex items-center justify-between pb-3 border-b border-[var(--border-subtle)]">
              <span className="text-[13px] font-medium text-[var(--text-strong)]">Parsed Markdown Document</span>
              <button
                type="button"
                onClick={() => copyToClipboard(activeFetch.document.markdown)}
                className="text-[13px] px-3 py-1 rounded bg-[var(--surface)] border border-[var(--border-subtle)] text-[var(--signal)] hover:text-white transition-colors"
              >
                {copied ? "Copied" : "Copy markdown"}
              </button>
            </div>

            <pre className="p-4 rounded-md bg-[var(--surface)] border border-[var(--border-subtle)] text-[13px] text-[var(--text)] whitespace-pre-wrap leading-relaxed max-h-[600px] overflow-auto">
              {activeFetch.document.markdown}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
