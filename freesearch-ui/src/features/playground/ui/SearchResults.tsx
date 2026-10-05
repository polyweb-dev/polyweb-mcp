import type { ReactNode } from "react"
import type { SearchResponse } from "@/domains/execution"
import { providerIdentity } from "@/domains/providers"
import { InspectorSplitPane } from "@/shared/ui/InspectorSplitPane"
import { JsonViewer } from "@/shared/ui/JsonViewer"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import type { PlaygroundController } from "../model/usePlaygroundController"
import { ResultCard } from "./ResultCard"
import { ResultInspector } from "./ResultInspector"
import { WaterfallPanel } from "./WaterfallPanel"

export interface SearchResultsProps {
  controller: PlaygroundController
  result: SearchResponse
}

/** Raw response inspector: one copy action over the shared collapsible viewer. */
function jsonInspector(search: SearchResponse, copied: boolean, onCopy: () => void): ReactNode {
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)]">
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-3 py-1.5">
        <span className="text-[12px] text-[var(--muted)]">Raw response</span>
        <button
          type="button"
          onClick={onCopy}
          className="text-[13px] text-[var(--signal)] hover:underline transition-colors"
        >
          {copied ? "Copied" : "Copy JSON"}
        </button>
      </div>
      <JsonViewer value={search} ariaLabel="Raw search response" className="p-3" />
    </div>
  )
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
  const resolvedIdentity = providerIdentity(activeSearch.selectedProviderId)
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
              {activeSearch.selectedProviderId === "aggregated" ? (
                <span>All Providers ({activeSearch.participatingProviders?.length ?? "multiple"} fused)</span>
              ) : (
                <ProviderBadge
                  providerId={resolvedIdentity.id}
                  name={resolvedIdentity.name}
                  logoClassName="size-3.5"
                />
              )}
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
      {showJsonInspector &&
        jsonInspector(activeSearch, copied, () =>
          copyToClipboard(JSON.stringify(activeSearch, null, 2))
        )}

      {/* Master/detail: results list beside the inspector and live telemetry.
          The split geometry is shared with the Activity dialog. */}
      <InspectorSplitPane
        primaryLabel="Returned results"
        detailLabel="Result inspector and execution waterfall"
        primary={
          <div className="min-w-0 space-y-3">
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
        }
        detail={
          <div className="min-w-0 space-y-6">
            <ResultInspector result={selectedResultForPreview} />

            {/* Waterfall Latency Diagnostics */}
            {activeSearch?.waterfall && activeSearch.waterfall.length > 0 && (
              <WaterfallPanel waterfall={activeSearch.waterfall} />
            )}
          </div>
        }
      />
    </div>
  )
}
