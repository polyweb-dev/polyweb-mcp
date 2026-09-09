import { ExternalLink } from "lucide-react"
import type { SearchResponse, SearchResult } from "@/types/freesearch"

type SearchResultInspectorOptions = {
  activeSearch: SearchResponse
  selectedResultForPreview: SearchResult | null
}

export function SearchResultInspector({
  activeSearch,
  selectedResultForPreview,
}: SearchResultInspectorOptions) {
  return (
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
  )
}
