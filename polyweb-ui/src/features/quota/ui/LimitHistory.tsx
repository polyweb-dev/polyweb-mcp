import { useState, type ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import { formatDateTime, formatRelativeTime } from "@/shared/lib/formatTime"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/shared/ui/table"
import type { UsdConversionProfile, LimitAuditEvent } from "@/domains/dashboard"
import { formatCallCost, formatCostTotal } from "@/domains/providers"
import { DEFAULT_TAVILY_PROFILE, formatCreditAmount, tavilyUsdToCredits } from "../model/tavilyCredits"
import { operationLabel, reasonLabel, sourceLabel } from "../model/quotaLabels"
import { newestFirst } from "../model/timeText"
import { groupDigits, nativeUnitLabel } from "../model/numberText"

export interface LimitHistoryProps {
  providerName: string
  events: LimitAuditEvent[]
  loading: boolean
  error: string | null
  hasMore: boolean
  onLoadMore: () => Promise<void>
  profile?: UsdConversionProfile
  nativeUnit?: string | null
}

const SYSTEM_SOURCES = ["local", "vendor_api", "vendor_headers", "local_ledger", "local_daily_estimate"]

function actorText(event: LimitAuditEvent): string {
  const actor = event.detail.actor
  if (typeof actor === "string" && actor.trim() !== "") return actor.trim()
  if (event.source === "operator" || event.source === "manual_anchor") return "Operator"
  return SYSTEM_SOURCES.includes(event.source) ? "System" : "Not recorded"
}

function nativeUnitText(event: LimitAuditEvent, fallback: string | null): string | null {
  if (event.provider === "tavily") return "credits"
  const unit = event.detail.native_unit
  return typeof unit === "string" && unit !== "" ? unit : fallback
}

function usdFromLedger(value: string): string {
  return formatCostTotal(value)
}

function nativeText(value: string, unit: string): string {
  if (unit.toUpperCase() === "USD") return formatCostTotal(value)
  if (unit.toUpperCase() === "FREE") return formatCallCost(0)
  return groupDigits(value) + " " + nativeUnitLabel(unit)
}

function balanceText(event: LimitAuditEvent, side: "old" | "new", profile: UsdConversionProfile | null, nativeUnit: string | null): string {
  const native = event.reason === "grant" ? null : side === "old" ? event.old_native : event.new_native
  const unit = nativeUnitText(event, nativeUnit)
  if (native !== null && unit !== null) return nativeText(native, unit)
  const amount = side === "old" ? event.old_usd : event.new_usd
  if (amount === null) return "Not recorded"
  if (event.provider === "tavily" && event.reason !== "grant") {
    const credits = tavilyUsdToCredits(amount, profile ?? DEFAULT_TAVILY_PROFILE)
    if (credits !== null) return formatCreditAmount(credits)
  }
  return usdFromLedger(amount)
}

function historySource(event: LimitAuditEvent): string {
  if (event.source === "vendor_api" || event.source === "vendor_headers") return "Provider API"
  if (event.reason === "manual_anchor" || event.source === "manual_anchor") return "Manual entry"
  if (["local", "local_ledger", "local_attempts", "local_daily_estimate"].includes(event.source)) return "Local usage"
  return sourceLabel(event.source) || "Not recorded"
}

function detailText(event: LimitAuditEvent): string {
  const operation = operationLabel(event.operation)
  const reason = event.reason === "vendor_sync" && event.source === "local_ledger" ? "Balance recorded" : reasonLabel(event.reason)
  return [operation, reason].filter((part) => part !== "").join(" · ")
}

function changeText(event: LimitAuditEvent, nativeUnit: string | null): string {
  const unit = nativeUnitText(event, nativeUnit)
  if (event.native_debit !== null && unit?.toUpperCase() === "USD") {
    return "−" + formatCostTotal(event.native_debit)
  }
  if (event.native_debit !== null && unit !== null) return "−" + nativeText(event.native_debit, unit)
  return event.debit_usd === null ? "Not recorded" : "−" + usdFromLedger(event.debit_usd)
}

export function LimitHistory({ providerName, events, loading, error, hasMore, onLoadMore, profile, nativeUnit = null }: LimitHistoryProps): ReactNode {
  const [now] = useState(Date.now)
  const rows = newestFirst(events)
  const hasChanges = events.some((event) => event.debit_usd !== null || event.native_debit !== null)
  return (
    <section aria-label={"Recorded changes for " + providerName} className="space-y-2">
      {loading && events.length === 0 && <p className="text-[12px] text-[var(--muted)]" role="status">Loading history…</p>}
      {error !== null && <p role="alert" className="rounded border border-[var(--status-danger)]/40 bg-[var(--surface)] p-2.5 text-[12px] text-[var(--status-danger)]">{error}</p>}
      {!loading && error === null && events.length === 0 && <p className="text-[12px] text-[var(--muted)]">No balance change recorded yet</p>}
      {events.length > 0 && (
        <Table aria-label={"Balance history for " + providerName} className="text-[12px]">
          <TableHeader><TableRow>
            <TableHead scope="col">Time</TableHead><TableHead scope="col">Old balance</TableHead>
            <TableHead scope="col">New balance</TableHead>{hasChanges && <TableHead scope="col">Change</TableHead>}
            <TableHead scope="col">Source</TableHead><TableHead scope="col">Actor</TableHead>
          </TableRow></TableHeader>
          <TableBody>{rows.map((event) => {
            const detail = detailText(event)
            return (
              <TableRow key={event.event_id}>
                <TableCell className="align-top">
                  <time className="tnum" dateTime={event.observed_at} title={formatDateTime(event.observed_at)}>{formatRelativeTime(Date.parse(event.observed_at), now)}</time>
                  {detail !== "" && <p className="text-[11px] text-[var(--muted)]">{detail}</p>}
                </TableCell>
                <TableCell className="tnum">{balanceText(event, "old", profile ?? null, nativeUnit)}</TableCell>
                <TableCell className="tnum">{balanceText(event, "new", profile ?? null, nativeUnit)}</TableCell>
                {hasChanges && <TableCell className="tnum">{changeText(event, nativeUnit)}</TableCell>}
                <TableCell>{historySource(event)}</TableCell><TableCell>{actorText(event)}</TableCell>
              </TableRow>
            )
          })}</TableBody>
        </Table>
      )}
      {hasMore && <Button type="button" variant="outline" size="sm" disabled={loading}
        aria-label={"Load older limit events for " + providerName} onClick={() => void onLoadMore()}>
        {loading ? "Loading…" : "Load older events"}
      </Button>}
    </section>
  )
}
