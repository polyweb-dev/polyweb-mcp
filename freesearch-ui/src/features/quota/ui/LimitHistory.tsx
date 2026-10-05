import type { ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import type { LimitAuditEvent } from "@/domains/dashboard"
import { formatCRDAmount } from "../model/crdDisplay"

export interface LimitHistoryProps {
  providerName: string
  events: LimitAuditEvent[]
  loading: boolean
  error: string | null
  hasMore: boolean
  onLoadMore: () => Promise<void>
}

function balanceText(oldValue: string | null, newValue: string | null): string {
  const before = oldValue === null ? "—" : formatCRDAmount(oldValue)
  const after = newValue === null ? "—" : formatCRDAmount(newValue)
  return before + " to " + after
}

function timeText(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

function headingId(providerName: string): string {
  return "limit-history-" + providerName.toLowerCase().replace(/[^a-z0-9]+/g, "-")
}

/**
 * Paged audit trail of one provider rail.
 *
 * Each row shows the observed time, the old and new credit-unit balance, the
 * source, and the reason. Amounts stay exact until this display rule rounds
 * them, so the ledger itself is never rewritten.
 */
export function LimitHistory({
  providerName,
  events,
  loading,
  error,
  hasMore,
  onLoadMore,
}: LimitHistoryProps): ReactNode {
  const id = headingId(providerName)
  return (
    <section aria-labelledby={id} className="space-y-2">
      <h5 id={id} className="text-[12px] font-semibold text-[var(--text-strong)]">
        Balance history
      </h5>
      {loading && events.length === 0 && (
        <p className="text-[12px] text-[var(--muted)]" role="status">
          Loading history…
        </p>
      )}
      {error !== null && (
        <p
          role="alert"
          className="rounded border border-[var(--status-danger)]/40 bg-[var(--surface)] p-2.5 text-[12px]"
          style={{ color: "var(--status-danger)" }}
        >
          {error}
        </p>
      )}
      {!loading && error === null && events.length === 0 && (
        <p className="text-[12px] text-[var(--muted)]">No balance change recorded yet.</p>
      )}
      {events.length > 0 && (
        <ul className="divide-y divide-[var(--border-subtle)] text-[12px]">
          {events.map((event) => (
            <li key={event.event_id} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1.5">
              <time className="tnum text-[var(--muted)]" dateTime={event.observed_at}>
                {timeText(event.observed_at)}
              </time>
              <span className="tnum text-[var(--text)]">{balanceText(event.old_crd, event.new_crd)}</span>
              <span className="text-[var(--muted)]">{event.source}</span>
              <span className="text-[var(--muted)]">{event.reason}</span>
            </li>
          ))}
        </ul>
      )}
      {hasMore && (
        <Button
          type="button"
          variant="outline"
          size="lg"
          className="px-3"
          disabled={loading}
          aria-label={"Load older limit events for " + providerName}
          onClick={() => void onLoadMore()}
        >
          {loading ? "Loading…" : "Load older events"}
        </Button>
      )}
    </section>
  )
}
