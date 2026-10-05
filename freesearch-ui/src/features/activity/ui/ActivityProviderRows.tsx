import type { ReactNode } from "react"
import { deriveProviderAttempts, type TraceProviderAttempt } from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { TableCell, TableRow } from "@/shared/ui/table"
import type { TraceLoadState } from "../model/useActivityController"
import { TraceStatusPill } from "./TraceStatusPill"

const CELL = "px-4 py-2"
/** Nested rows sit one shade above the page so the hierarchy is visible. */
const CHILD_ROW = { background: "color-mix(in srgb, var(--elevated) 55%, transparent)" }

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
      text: `Provider responses unavailable — ${state.error ?? "unknown error"}`,
      showRetry: true,
    }
  }
  if (state.detail === null) {
    return { kind: "message", tone: "quiet", text: "Loading provider responses...", showRetry: false }
  }
  const attempts = deriveProviderAttempts(state.detail.stages, state.detail.provider)
  if (attempts.length === 0) {
    return {
      kind: "message",
      tone: "quiet",
      text: "No provider attempt was recorded for this trace.",
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
    <TableRow key={rowId} id={rowId} className="border-b border-[var(--border-subtle)] last:border-b-0">
      <TableCell colSpan={7} className={`${CELL} whitespace-normal`} style={CHILD_ROW}>
        <span className="flex flex-wrap items-center gap-3 pl-4">
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
      </TableCell>
    </TableRow>
  )
}

function attemptRow(
  attempt: TraceProviderAttempt,
  first: boolean,
  rowId: string,
  onInspect: (providerSpanId: string) => void
): ReactNode {
  return (
    <TableRow
      key={attempt.spanId}
      {...(first ? { id: rowId } : {})}
      className="border-b border-[var(--border-subtle)] last:border-b-0"
      style={CHILD_ROW}
    >
      <TableCell className={`${CELL} pl-8 text-[var(--accent-cyan)]`} aria-hidden="true">
        ↳
      </TableCell>
      <TableCell className={`${CELL} text-[var(--muted)]`}>response</TableCell>
      <TableCell className={`${CELL} text-[var(--text-strong)]`}>
        {providerValue(attempt)}
      </TableCell>
      <TableCell className={`${CELL} text-center`}>
        <TraceStatusPill outcome={attempt.outcome} />
      </TableCell>
      <TableCell className={`${CELL} text-right text-[var(--text)] tnum`}>
        {attempt.durationMs}ms
      </TableCell>
      <TableCell className={`${CELL} text-right text-[var(--muted)] tnum`}>
        {resultLabel(attempt)}
      </TableCell>
      <TableCell className={`${CELL} text-right`}>
        <Button variant="outline" size="default" onClick={() => onInspect(attempt.spanId)}>
          View details
        </Button>
      </TableCell>
    </TableRow>
  )
}

/**
 * Nested provider rows for one expanded fanout trace: one row per
 * `freesearch.provider` span, with the loading/error/retry state occupying a
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
