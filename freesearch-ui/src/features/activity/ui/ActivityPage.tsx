import { RefreshCw } from "lucide-react"
import { useSearchParams } from "react-router"
import type { TraceOperation, TraceOutcome } from "@/domains/activity"
import { useProjectScope } from "@/domains/projects"
import { Button } from "@/shared/ui/button"
import { SegmentedControl } from "@/shared/ui/SegmentedControl"
import { filtersFromSearch, filtersToSearch } from "../model/activityFilters"
import type { ActivityFilters } from "../model/activityFilters"
import { selectedTraceState, useActivityController } from "../model/useActivityController"
import { ActivityList } from "./ActivityList"
import { ActivityLoadMore } from "./ActivityLoadMore"
import { TraceDetailDialog } from "./TraceDetailDialog"

const OPERATION_LABELS: ReadonlyArray<readonly [TraceOperation | null, string]> = [
  [null, "All"],
  ["search", "Search"],
  ["fetch", "Fetch"],
]

const OUTCOME_LABELS: ReadonlyArray<readonly [TraceOutcome | null, string]> = [
  [null, "All"],
  ["success", "Success"],
  ["partial", "Partial"],
  ["error", "Error"],
]

function labelOf<T>(labels: ReadonlyArray<readonly [T | null, string]>, value: T | null): string {
  return labels.find(([candidate]) => candidate === value)?.[1] ?? "All"
}

function valueOf<T>(labels: ReadonlyArray<readonly [T | null, string]>, label: string): T | null {
  return labels.find(([, candidate]) => candidate === label)?.[0] ?? null
}

/**
 * Activity page of the URL project: the traces this project recorded for its
 * provider calls, newest first. The Operation and Outcome filters live in the
 * URL query, so a filter change reloads page one and a reload keeps it. The
 * list is deliberately payload-free (time, operation, provider, status,
 * latency, result count); everything sensitive lives behind the explicit
 * "View details" disclosure, and closing it keeps the loaded rows.
 */
export function ActivityPage() {
  const { projectId } = useProjectScope()
  const [params, setParams] = useSearchParams()
  const filters = filtersFromSearch(params)
  const controller = useActivityController(projectId, filters)
  const setFilters = (next: Partial<ActivityFilters>) =>
    setParams((current) => filtersToSearch(current, { ...filters, ...next }), { replace: true })
  const selection = controller.selection
  const state = selectedTraceState(controller)

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 border-b border-[var(--border-subtle)] pb-3 mb-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-xl font-medium text-[var(--text-strong)]">Activity</h2>
          <p className="mt-0.5 truncate text-[13px] text-[var(--muted)]">
            This project's recorded search and fetch traces, stage by stage.
          </p>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <SegmentedControl
            options={OPERATION_LABELS.map(([, label]) => label)}
            value={labelOf(OPERATION_LABELS, filters.operation)}
            onChange={(label) => setFilters({ operation: valueOf(OPERATION_LABELS, label) })}
            ariaLabel="Operation"
          />
          <SegmentedControl
            options={OUTCOME_LABELS.map(([, label]) => label)}
            value={labelOf(OUTCOME_LABELS, filters.outcome)}
            onChange={(label) => setFilters({ outcome: valueOf(OUTCOME_LABELS, label) })}
            ariaLabel="Outcome"
          />
          <Button
            variant="default"
            size="icon-lg"
            className="h-auto w-[34px] self-stretch"
            onClick={controller.refresh}
            aria-label="Refresh"
            title="Refresh"
          >
            <RefreshCw aria-hidden="true" className="size-4" />
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
          <Button variant="outline" size="form" onClick={controller.refresh}>
            Retry
          </Button>
        </div>
      )}

      {controller.listStatus === "ready" && controller.summaries.length === 0 && (
        <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] p-12 text-center">
          <p className="text-[13px] text-[var(--muted)]">
            {filters.operation === null && filters.outcome === null
              ? "No traces recorded yet. Run a search or fetch in the Playground to populate them."
              : "No traces match these filters."}
          </p>
        </div>
      )}

      {controller.listStatus === "ready" && controller.summaries.length > 0 && (
        <>
          <ActivityList
            summaries={controller.summaries}
            expandedTraceId={controller.expandedTraceId}
            detailsById={controller.detailsById}
            onSelect={controller.openTrace}
            onToggleProviders={controller.toggleProviders}
            onInspect={controller.openTrace}
            onRetry={controller.retryTrace}
          />
          <ActivityLoadMore controller={controller} />
        </>
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
