import { ProviderLogo } from "@/components/common/ProviderLogo"
import type { SearchResponse } from "@/types/freesearch"

type SearchResultsSummaryOptions = {
  activeSearch: SearchResponse
  showJsonInspector: boolean
  copied: boolean
  onToggleJsonInspector: () => void
  onCopy: (text: string) => void
}

export function SearchResultsSummary({
  activeSearch,
  showJsonInspector,
  copied,
  onToggleJsonInspector,
  onCopy,
}: SearchResultsSummaryOptions) {
  return (
    <>
      {/* Telemetry bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 text-[13px] py-3.5 px-4.5 rounded-xl bg-[var(--elevated)] border border-[var(--border-subtle)] text-[var(--muted)]">
        <div className="flex flex-wrap items-center gap-6 sm:gap-8 tnum">
          <div className="flex items-center gap-2">
            <span>Latency</span>
            <span className="font-medium text-[var(--text-strong)]">{activeSearch.executionTimeMs}ms</span>
          </div>
          <div className="flex items-center gap-2">
            <span>Units</span>
            <span className="font-medium text-[var(--text-strong)]">{activeSearch.costEstimateCredits}</span>
          </div>
          <div className="flex items-center gap-2">
            <span>Resolved by</span>
            <span className="inline-flex items-center gap-1.5 font-medium text-[var(--signal)]">
              <ProviderLogo providerId={activeSearch.selectedProviderId} className="size-3.5" />
              {activeSearch.selectedProviderId}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span>Results</span>
            <span className="font-medium text-[var(--text-strong)]">{activeSearch.results.length}</span>
          </div>
        </div>

        <button
          type="button"
          onClick={onToggleJsonInspector}
          className="text-[13px] font-medium text-[var(--signal)] hover:underline transition-colors"
        >
          {showJsonInspector ? "Hide raw JSON" : "Inspect raw JSON"}
        </button>
      </div>

      {/* JSON inspector toggle */}
      {showJsonInspector && (
        <div className="relative border border-[var(--border-subtle)] rounded-lg overflow-hidden">
          <button
            type="button"
            onClick={() => onCopy(JSON.stringify(activeSearch, null, 2))}
            className="absolute top-3 right-3 text-[13px] text-[var(--signal)] hover:underline bg-[var(--surface)] px-2 py-1 rounded border border-[var(--border-subtle)]"
          >
            {copied ? "Copied" : "Copy JSON"}
          </button>
          <pre className="p-4 text-[13px] font-mono leading-relaxed max-h-72 overflow-auto bg-[var(--elevated)] text-[var(--text)]">
            {JSON.stringify(activeSearch, null, 2)}
          </pre>
        </div>
      )}
    </>
  )
}
