import { ProviderLogo } from "@/components/common/ProviderLogo"
import type { SearchResponse } from "@/types/freesearch"
import type { PlaygroundController } from "../model/usePlaygroundController"
import { ResultCard } from "./ResultCard"
import { ResultInspector } from "./ResultInspector"
import { WaterfallPanel } from "./WaterfallPanel"

export interface SearchResultsProps {
  controller: PlaygroundController
  result: SearchResponse
}

/** Widescreen search results: telemetry bar, JSON inspector, list + inspector. */
export function SearchResults({ controller, result: activeSearch }: SearchResultsProps) {
  const {
    selectedResultForPreview,
    setSelectedResultForPreview,
    showJsonInspector,
    setShowJsonInspector,
    copied,
    copyToClipboard,
    isSearching,
    isFetching,
    handleFetchResult,
  } = controller
  return (
    <div className="space-y-6 pt-2">
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
          onClick={() => setShowJsonInspector(!showJsonInspector)}
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
            {activeSearch.results.map((res) => (
              <ResultCard
                key={res.id}
                result={res}
                selected={selectedResultForPreview?.id === res.id}
                isSearching={isSearching}
                isFetching={isFetching}
                onSelect={setSelectedResultForPreview}
                onFetch={(selected) => void handleFetchResult(selected)}
              />
            ))}
          </div>
        </div>

        {/* Right Column: Live Result Inspector & Waterfall Telemetry */}
        <div className="lg:col-span-5 space-y-6">
          <ResultInspector result={selectedResultForPreview} />

          {/* Waterfall Latency Diagnostics */}
          {activeSearch?.waterfall && activeSearch.waterfall.length > 0 && (
            <WaterfallPanel waterfall={activeSearch.waterfall} />
          )}
        </div>
      </div>
    </div>
  )
}
