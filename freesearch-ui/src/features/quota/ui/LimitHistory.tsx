import type { ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/ui/table"
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

const SYSTEM_SOURCES = [
  "local",
  "vendor_api",
  "vendor_headers",
  "local_ledger",
  "local_daily_estimate",
]

/** One explicit actor identity, else the actor category of the audit source. */
function actorText(event: LimitAuditEvent): string {
  const actor = event.detail.actor
  if (typeof actor === "string" && actor.trim() !== "") return actor.trim()
  if (event.source === "operator" || event.source === "manual_anchor") return "Operator"
  return SYSTEM_SOURCES.includes(event.source) ? "System" : ""
}

/** Unit of a native amount; the detail says it, else the amount stays generic. */
function nativeUnitText(event: LimitAuditEvent): string {
  const unit = event.detail.native_unit
  return typeof unit === "string" && unit !== "" ? unit : "native"
}

/** Visible text of one side of a balance change: credit units first, then native units. */
function balanceText(event: LimitAuditEvent, side: "old" | "new"): string {
  const crd = side === "old" ? event.old_crd : event.new_crd
  if (crd !== null) return formatCRDAmount(crd)
  const native = side === "old" ? event.old_native : event.new_native
  return native === null ? "" : native + " " + nativeUnitText(event)
}

function timeText(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

function headingId(providerName: string): string {
  return "limit-history-" + providerName.toLowerCase().replace(/[^a-z0-9]+/g, "-")
}

/** Known operation and reason of one event, joined as one supplementary line. */
function detailText(event: LimitAuditEvent): string {
  return [event.operation, event.reason].filter((part): part is string => Boolean(part)).join(" · ")
}

/**
 * Paged audit trail of one provider rail.
 *
 * Each row shows the observed time, the old and new credit-unit balance, the
 * source, and the actor. Amounts stay exact until this display rule rounds
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
        <Table aria-label={"Balance history for " + providerName} className="text-[12px]">
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Time</TableHead>
              <TableHead scope="col">Old balance</TableHead>
              <TableHead scope="col">New balance</TableHead>
              <TableHead scope="col">Source</TableHead>
              <TableHead scope="col">Actor</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((event) => {
              const detail = detailText(event)
              return (
                <TableRow key={event.event_id}>
                  <TableCell className="align-top">
                    <time className="tnum" dateTime={event.observed_at}>
                      {timeText(event.observed_at)}
                    </time>
                    {detail !== "" && (
                      <p className="text-[11px] text-[var(--muted)]">{detail}</p>
                    )}
                  </TableCell>
                  <TableCell className="tnum">{balanceText(event, "old")}</TableCell>
                  <TableCell className="tnum">{balanceText(event, "new")}</TableCell>
                  <TableCell>{event.source}</TableCell>
                  <TableCell>{actorText(event)}</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
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
