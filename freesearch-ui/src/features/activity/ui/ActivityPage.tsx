import { Button } from "@/shared/ui/button"
import { SegmentedControl } from "@/shared/ui/SegmentedControl"
import type { ActivityFilter } from "../model/useActivityController"
import { selectedTraceState, useActivityController } from "../model/useActivityController"
import { ActivityList } from "./ActivityList"
import { TraceDetailDialog } from "./TraceDetailDialog"

const FILTER_LABELS: Record<ActivityFilter, string> = {
  all: "All",
  search: "Search",
  fetch: "Fetch",
}

const FILTER_OPTIONS = ["All", "Search", "Fetch"] as const

function filterFromLabel(label: string): ActivityFilter {
  const match = (Object.keys(FILTER_LABELS) as ActivityFilter[]).find(
    (filter) => FILTER_LABELS[filter] === label
  )
  return match ?? "all"
}

/**
 * Activity page: the traces this backend actually recorded for its provider
 * calls. The list is deliberately payload-free (time, operation, provider,
 * status, latency, result count); everything sensitive lives behind the
 * explicit "View details" disclosure.
 */
export function ActivityPage() {
  const controller = useActivityController()
  const selection = controller.selection
  const state = selectedTraceState(controller)

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 border-b border-[var(--border-subtle)] pb-2 sm:flex-row sm:items-baseline sm:justify-between">
        <div>
          <h2 className="text-[var(--text-strong)]">Activity</h2>
          <p className="mt-0.5 text-[13px] text-[var(--muted)]">
            Recorded search and fetch traces, stage by stage.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <SegmentedControl
            options={FILTER_OPTIONS}
            value={FILTER_LABELS[controller.filter]}
            onChange={(label) => controller.setFilter(filterFromLabel(label))}
            ariaLabel="Activity operation filter"
          />
          <Button variant="outline" size="sm" onClick={controller.refresh}>
            Refresh
          </Button>
        </div>
      </div>

      {controller.listStatus === "loading" && (
        <p className="p-8 text-center text-[13px] text-[var(--muted)]" role="status">
          Loading activity traces...
        </p>
      )}

      {controller.listStatus === "error" && (
        <div className="space-y-3">
          <p role="alert" className="text-[13px]" style={{ color: "var(--status-danger)" }}>
            Activity traces unavailable — {controller.listError}
          </p>
          <Button variant="outline" size="sm" onClick={controller.refresh}>
            Retry
          </Button>
        </div>
      )}

      {controller.listStatus === "ready" && controller.summaries.length === 0 && (
        <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] p-12 text-center">
          <p className="text-[13px] text-[var(--muted)]">
            No traces recorded yet. Run a search or fetch in the Playground to populate them.
          </p>
        </div>
      )}

      {controller.listStatus === "ready" && controller.summaries.length > 0 && (
        <ActivityList
          summaries={controller.summaries}
          expandedTraceId={controller.expandedTraceId}
          detailsById={controller.detailsById}
          onSelect={controller.openTrace}
          onToggleProviders={controller.toggleProviders}
          onInspect={controller.openTrace}
          onRetry={controller.retryTrace}
        />
      )}

      <TraceDetailDialog
        isOpen={selection !== null}
        trace={state.detail}
        providerSpanId={selection?.providerSpanId ?? null}
        status={state.status === "idle" ? "loading" : state.status}
        error={state.error}
        onClose={controller.closeTrace}
        onRetry={() => selection !== null && controller.retryTrace(selection.traceId)}
      />
    </div>
  )
}
