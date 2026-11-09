import type { ReactNode } from "react"
import { deriveProviderAttempts, type TraceProviderAttempt } from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { formatLatency } from "@/shared/lib/formatTime"
import { Button } from "@/shared/ui/button"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import type { TraceLoadState } from "../model/useActivityController"
import { ActivityRowAction } from "./ActivityRowAction"
import { TraceStatusPill } from "./TraceStatusPill"

/** Nested rows sit one shade above the page so the hierarchy is visible. */
const CHILD_CELL = "bg-[color-mix(in_srgb,var(--elevated)_55%,transparent)]"
const COLUMN_COUNT = 7

export interface ActivityProviderRowsProps {
  /** Id the parent row's expander points at with `aria-controls`. */
  rowId: string
  state: TraceLoadState | undefined
  onInspect: (providerSpanId: string) => void
  onRetry: () => void
}

type PanelView =
  | { kind: "message"; tone: "quiet" | "error"; text: string; showRetry: boolean }
  | { kind: "attempts"; attempts: TraceProviderAttempt[] }

function panelView(state: TraceLoadState | undefined): PanelView {
  if (state === undefined || state.status === "loading" || state.status === "idle") {
    return { kind: "message", tone: "quiet", text: "Loading provider responses...", showRetry: false }
  }
  if (state.status === "error") {
    return {
      kind: "message",
      tone: "error",
      text: `Provider responses unavailable: ${state.error ?? "unknown error"}`,
      showRetry: true,
    }
  }
  if (state.status === "missing") {
    return { kind: "message", tone: "quiet", text: state.error ?? "", showRetry: false }
  }
  if (state.detail === null) {
    return { kind: "message", tone: "quiet", text: "Loading provider responses...", showRetry: false }
  }
  const attempts = deriveProviderAttempts(state.detail.stages, state.detail.provider)
  if (attempts.length === 0) {
    return {
      kind: "message",
      tone: "quiet",
      text: "No provider attempt was recorded for this trace",
      showRetry: false,
    }
  }
  return { kind: "attempts", attempts }
}

function resultLabel(attempt: TraceProviderAttempt): string {
  return attempt.resultCount === null ? "—" : String(attempt.resultCount)
}

/** The recorded attempt identity, with an explicit note when nothing named it. */
function providerValue(attempt: TraceProviderAttempt): ReactNode {
  if (attempt.providerId === null || attempt.providerId === "") {
    return (
      <>
        {attempt.providerLabel}
        <span className="ml-1.5 text-[11px] text-[var(--muted)]">Name not recorded</span>
      </>
    )
  }
  const identity = providerIdentity(attempt.providerId)
  if (identity.id === "") return attempt.providerLabel
  return <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-3.5" />
}

function messageRow(
  rowId: string,
  view: Extract<PanelView, { kind: "message" }>,
  onRetry: () => void
): ReactNode {
  return (
    <tr key={rowId} id={rowId}>
      <td colSpan={COLUMN_COUNT} className={`${CHILD_CELL} whitespace-normal`}>
        <span className="flex flex-wrap items-center gap-3 pl-6">
          <span
            role={view.tone === "error" ? "alert" : "status"}
            className="text-[12px]"
            style={{ color: view.tone === "error" ? "var(--status-danger)" : "var(--muted)" }}
          >
            {view.text}
          </span>
          {view.showRetry && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          )}
        </span>
      </td>
    </tr>
  )
}

function attemptRow(
  attempt: TraceProviderAttempt,
  first: boolean,
  rowId: string,
  onInspect: (providerSpanId: string) => void
): ReactNode {
  return (
    <tr
      key={attempt.spanId}
      {...(first ? { id: rowId } : {})}
      onClick={() => onInspect(attempt.spanId)}
      className="relative cursor-pointer"
    >
      <td className={`${CHILD_CELL} pl-8 text-[var(--muted)]`} aria-hidden="true">
        ↳
      </td>
      <td className={`${CHILD_CELL} text-[var(--muted)]`}>Response</td>
      <td className={`${CHILD_CELL} fs-cell-strong`}>{providerValue(attempt)}</td>
      <td className={CHILD_CELL}>
        <TraceStatusPill outcome={attempt.outcome} />
      </td>
      <td className={`${CHILD_CELL} tnum text-right`}>{formatLatency(attempt.durationMs)}</td>
      <td className={`${CHILD_CELL} tnum text-right text-[var(--muted)]`}>
        {resultLabel(attempt)}
      </td>
      <td className={`${CHILD_CELL} fs-cell-actions`}>
        <ActivityRowAction onOpen={() => onInspect(attempt.spanId)} />
      </td>
    </tr>
  )
}

/**
 * Nested provider rows for one expanded fanout trace: one row per
 * `polyweb.provider` span, with the loading/error/retry state occupying a
 * single wrapping row. Response payloads are deliberately not rendered here —
 * they belong to the detail dialog.
 */
export function ActivityProviderRows({
  rowId,
  state,
  onInspect,
  onRetry,
}: ActivityProviderRowsProps) {
  const view = panelView(state)
  if (view.kind === "message") return messageRow(rowId, view, onRetry)
  return (
    <>
      {view.attempts.map((attempt, index) =>
        attemptRow(attempt, index === 0, rowId, onInspect)
      )}
    </>
  )
}
