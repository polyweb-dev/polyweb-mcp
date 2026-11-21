import { useState } from "react"
import type { ReactNode } from "react"
import { searchTraceRef } from "@/domains/execution"
import type { SearchResponse, SearchTraceRef } from "@/domains/execution"
import { getProviderPrices, providerIdentity } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { formatLatency } from "@/shared/lib/formatTime"
import { Button } from "@/shared/ui/button"
import { InspectorSplitPane } from "@/shared/ui/InspectorSplitPane"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import type { RenderTraceDetails } from "../model/traceDetailsSlot"
import type { PlaygroundController } from "../model/usePlaygroundController"
import { usageTelemetry } from "../model/usageTelemetry"
import { ResultCard } from "./ResultCard"
import { ResultInspector } from "./ResultInspector"
import { WaterfallPanel } from "./WaterfallPanel"

export interface SearchResultsProps {
  controller: PlaygroundController
  result: SearchResponse
  renderTraceDetails: RenderTraceDetails
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

/** Widescreen search results: telemetry bar with View details, list + inspector. */
export function SearchResults({ controller, result: activeSearch, renderTraceDetails }: SearchResultsProps) {
  // The open popup keeps the trace of the result the user clicked, even when
  // a search that was still running replaces the results underneath it.
  const [openTrace, setOpenTrace] = useState<SearchTraceRef | null>(null)
  const {
    selectedResultForPreview,
    setSelectedResultForPreview,
    isSearching,
    isFetching,
    canFetch,
    handleFetchResult,
  } = controller
  const needsPrice = activeSearch.costUnitKind !== "USD" && activeSearch.costUnitKind !== "FREE" &&
    activeSearch.selectedProviderId !== "aggregated"
  const prices = useScopedResource({
    scopeKey: activeSearch.selectedProviderId,
    load: getProviderPrices,
    enabled: needsPrice,
  })
  const price = prices.status === "ready" ? prices.data.find((item) =>
    providerIdentity(item.providerType).id === providerIdentity(activeSearch.selectedProviderId).id) : undefined
  const usage = usageTelemetry(activeSearch, price)
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
        </div>

        <Button
          type="button"
          variant="ghost"
          size="form"
          aria-haspopup="dialog"
          onClick={() => setOpenTrace(searchTraceRef(activeSearch))}
        >
          View details
        </Button>
      </div>

      {openTrace !== null && renderTraceDetails({ ...openTrace, onClose: () => setOpenTrace(null) })}

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
