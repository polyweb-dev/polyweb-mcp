import { RefreshCw } from "lucide-react"
import { useSearchParams } from "react-router"
import type { TraceOperation, TraceOutcome } from "@/domains/activity"
import { useProjectScope } from "@/domains/projects"
import { Button } from "@/shared/ui/button"
import { EmptyState } from "@/shared/ui/EmptyState"
import { PageHeader } from "@/shared/ui/PageHeader"
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

/** Empty-list copy: nothing recorded yet, or nothing matching the filters. */
function emptyCopy(filters: ActivityFilters): { title: string; description: string } {
  if (filters.operation === null && filters.outcome === null) {
    return {
      title: "No traces recorded yet",
      description: "Run a search or fetch in the Playground to record one",
    }
  }
  return { title: "No traces match these filters", description: "Choose All to see every trace" }
}

function valueOf<T>(labels: ReadonlyArray<readonly [T | null, string]>, label: string): T | null {
  return labels.find(([, candidate]) => candidate === label)?.[0] ?? null
}

/** One labelled filter group: a quiet caption, then the shared segmented control. */
function filterGroup<T>(
  label: string,
  labels: ReadonlyArray<readonly [T | null, string]>,
  value: T | null,
  onChange: (next: T | null) => void
) {
  return (
    <div className="flex items-center gap-2">
      <span aria-hidden="true" className="text-[13px] text-[var(--muted)]">
        {label}
      </span>
      <SegmentedControl
        options={labels.map(([, option]) => option)}
        value={labelOf(labels, value)}
        onChange={(option) => onChange(valueOf(labels, option))}
        ariaLabel={label}
      />
    </div>
  )
}

/**
 * Activity page of the URL project: the traces this project recorded for its
 * provider calls, newest first. The Operation and Outcome filters live in the
 * URL query, so a filter change reloads page one and a reload keeps it. The
 * list is payload-free; the query and results live behind the trace detail,
 * and closing it keeps the loaded rows.
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
    <div className="space-y-4">
      <PageHeader
        title="Activity"
        description="Every search and fetch this project ran"
        actions={
          <Button variant="outline" size="sm" onClick={controller.refresh}>
            <RefreshCw aria-hidden="true" />
            Refresh
          </Button>
        }
      />
      <div className="flex flex-wrap items-center gap-6">
        {filterGroup("Operation", OPERATION_LABELS, filters.operation, (operation) =>
          setFilters({ operation })
        )}
        {filterGroup("Outcome", OUTCOME_LABELS, filters.outcome, (outcome) =>
          setFilters({ outcome })
        )}
      </div>

      {controller.listStatus === "loading" && (
        <p className="p-8 text-center text-[13px] text-[var(--muted)]" role="status">
          Loading activity…
        </p>
      )}

      {controller.listStatus === "error" && (
        <div className="space-y-3">
          <p role="alert" className="text-[13px]" style={{ color: "var(--status-danger)" }}>
            Couldn't load activity: {controller.listError}
          </p>
          <Button variant="outline" size="form" onClick={controller.refresh}>
            Retry
          </Button>
        </div>
      )}

      {controller.listStatus === "ready" && controller.summaries.length === 0 && (
        <EmptyState {...emptyCopy(filters)} />
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
