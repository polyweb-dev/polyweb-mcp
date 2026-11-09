import type { ReactNode } from "react"
import type { SearchResponse } from "@/domains/execution"
import { providerIdentity } from "@/domains/providers"
import { formatLatency } from "@/shared/lib/formatTime"
import { Button } from "@/shared/ui/button"
import { InspectorSplitPane } from "@/shared/ui/InspectorSplitPane"
import { JsonViewer } from "@/shared/ui/JsonViewer"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import type { PlaygroundController } from "../model/usePlaygroundController"
import { usageTelemetry } from "../model/usageTelemetry"
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
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-3 py-1">
        <span className="text-[12px] text-[var(--muted)]">Raw response</span>
        <Button type="button" variant="ghost" size="sm" onClick={onCopy}>
          {copied ? "Copied" : "Copy JSON"}
        </Button>
      </div>
      <JsonViewer value={search} ariaLabel="Raw search response" className="p-3" />
    </div>
  )
}

/** One label/value pair of the telemetry bar. */
function telemetryItem(label: string, value: ReactNode): ReactNode {
  return (
    <div className="flex items-center gap-2">
      <span>{label}</span>
      <span className="font-medium text-[var(--text-strong)]">{value}</span>
    </div>
  )
}

/** Who answered: the provider's logo and name, or the fused provider count. */
function resolvedBy(search: SearchResponse): ReactNode {
  if (search.selectedProviderId === "aggregated") {
    return <span>All providers ({search.participatingProviders?.length ?? "multiple"} fused)</span>
  }
  const identity = providerIdentity(search.selectedProviderId)
  return <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-3.5" />
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
    canFetch,
    handleFetchResult,
  } = controller
  const usage = usageTelemetry(activeSearch)
  const showAttribution = new Set(activeSearch.results.flatMap((result) =>
    (result.sources?.length ? result.sources : [result.providerId]).map((id) => providerIdentity(id).id)
  )).size > 1
  return (
    <div className="space-y-6 pt-2">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--elevated)] py-2 pl-4 pr-2 text-[13px] text-[var(--muted)]">
        <div className="flex flex-wrap items-center gap-6 sm:gap-8 tnum">
          {telemetryItem("Latency", formatLatency(activeSearch.executionTimeMs))}
          {telemetryItem(usage.label, usage.value)}
          {telemetryItem("Resolved by", resolvedBy(activeSearch))}
          {telemetryItem("Results", activeSearch.results.length)}
        </div>

        <Button
          type="button"
          variant="ghost"
          size="form"
          aria-expanded={showJsonInspector}
          onClick={() => setShowJsonInspector(!showJsonInspector)}
        >
          {showJsonInspector ? "Hide raw JSON" : "Inspect raw JSON"}
        </Button>
      </div>

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
            <p className="pb-1 text-[13px] text-[var(--muted)]">
              Returned results ({activeSearch.results.length})
            </p>

            <div className="space-y-2">
              {activeSearch.results.map((res) => (
                <ResultCard
                  key={res.id}
                  result={res}
                  selected={selectedResultForPreview?.id === res.id}
                  isSearching={isSearching}
                  isFetching={isFetching}
                  canFetch={canFetch}
                  showAttribution={showAttribution}
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
