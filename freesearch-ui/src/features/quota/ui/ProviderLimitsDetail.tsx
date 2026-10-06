import type { ReactNode } from "react"
import type {
  CRDGrantsSummary,
  CRDView,
  LimitRateWindow,
  NativePool,
  ProviderAuthLimits,
  ProviderLimitDetail,
} from "@/domains/dashboard"
import { dollarText, formatCRDAmount, resetRuleText } from "../model/crdDisplay"
import { operationAvailable } from "../model/crdCardModel"
import { poolName, SPEND_CAP } from "../model/quotaLabels"
import { dateText, timestampOrNull } from "../model/timeText"

export interface ProviderLimitsDetailProps {
  providerName: string
  auth: ProviderAuthLimits
}

/** Value family of one row: the credit-unit block comes first and the USD block goes last. */
type RowKind = "crd" | "plain" | "usd"
const ROW_ORDER: RowKind[] = ["crd", "plain", "usd"]

interface DetailRow {
  kind: RowKind
  label: string
  value: string
}

const WINDOW_TEXT: Record<string, string> = {
  "1s": "second",
  "1m": "minute",
  "1h": "hour",
  "1d": "day",
}
/** Only second and minute windows need text; the hour and day bars carry their own. */
const TEXT_WINDOWS = ["1s", "1m"]

/** Known text only: an absent, empty, or unknown value yields no row. */
function known(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "" || text.toLowerCase() === "unknown" || text === "n/a") return null
  return text
}

/** A native amount of the USD unit uses the dollar form; any other unit keeps its own name. */
function nativeText(amountValue: string | null, unit: string | null): string | null {
  const text = known(amountValue)
  if (text === null) return null
  const label = known(unit)
  if (label === null) return text
  return label.toUpperCase() === "USD" ? dollarText(text) : text + " " + label
}

/** A USD amount belongs to the USD block; any other native unit stays a plain fact. */
function amountKind(unit: string | null): RowKind {
  const label = known(unit)
  return label !== null && label.toUpperCase() === "USD" ? "usd" : "plain"
}

/** Only http and https links become anchors; any other text stays plain. */
function safeHref(url: string | null): string | null {
  if (url === null) return null
  return /^https?:\/\//i.test(url) ? url : null
}

function push(rows: DetailRow[], kind: RowKind, label: string, value: string | null): void {
  if (value !== null) rows.push({ kind, label, value })
}

function planText(detail: ProviderLimitDetail | null, auth: ProviderAuthLimits): string | null {
  return known(detail?.plan_name ?? null) ?? known(auth.search?.plan_name ?? null)
}

/** Only a known reset rule becomes a row; an unknown rule stays absent. */
function resetText(detail: ProviderLimitDetail | null): string | null {
  if (detail === null || detail.reset_rule === "unknown") return null
  return resetRuleText(detail.reset_rule, detail.reset_at)
}

function detailRows(detail: ProviderLimitDetail | null, plan: string | null): DetailRow[] {
  const rows: DetailRow[] = []
  if (detail === null) return rows
  const unit = detail.native_unit
  push(rows, "plain", "Plan", plan)
  push(rows, amountKind(unit), "Remaining balance", nativeText(detail.native_balance, unit))
  push(rows, amountKind(unit), "Native allowance", nativeText(detail.native_allowance, unit))
  push(rows, "usd", "USD per call", known(detail.usd_per_call))
  push(rows, "usd", "Vendor-reported USD spend", known(detail.actual_spend_usd))
  push(rows, "plain", "Reset", resetText(detail))
  push(rows, "plain", "Last sync", timestampOrNull(detail.last_sync_at))
  return rows
}

function grantText(granted: string, consumed: string): string {
  return formatCRDAmount(granted) + " set, " + formatCRDAmount(consumed) + " used"
}

/** Spend cap facts of the supported operations only. */
function grantRows(grants: CRDGrantsSummary | null, auth: ProviderAuthLimits): DetailRow[] {
  const rows: DetailRow[] = []
  if (grants === null) return rows
  const start = known(grants.period_start)
  const end = known(grants.period_end)
  const period = start === null || end === null ? null : dateText(start) + " to " + dateText(end)
  push(rows, "plain", SPEND_CAP + " period", period)
  if (operationAvailable(auth, "search")) {
    push(rows, "crd", "Search " + SPEND_CAP.toLowerCase(), grantText(grants.search_granted_crd, grants.search_consumed_crd))
  }
  if (operationAvailable(auth, "fetch")) {
    push(rows, "crd", "Fetch " + SPEND_CAP.toLowerCase(), grantText(grants.fetch_granted_crd, grants.fetch_consumed_crd))
  }
  return rows
}

/** Known parts of one operation cost: the cost, its call volume, and its local ceiling. */
function viewRow(label: string, view: CRDView | undefined): DetailRow | null {
  if (view === undefined) return null
  const parts: string[] = []
  const cost = known(view.request_cost_crd)
  if (cost !== null) parts.push(formatCRDAmount(cost) + " per standard call")
  const calls = known(view.possible_standard_calls)
  if (calls !== null) parts.push(calls + " calls left")
  const ceiling = known(view.local_remaining_crd)
  if (ceiling !== null) parts.push("local ceiling " + formatCRDAmount(ceiling))
  return parts.length === 0 ? null : { kind: "crd", label, value: parts.join(", ") }
}

function viewRows(auth: ProviderAuthLimits): DetailRow[] {
  const rows: DetailRow[] = []
  for (const operation of ["search", "fetch"] as const) {
    if (!operationAvailable(auth, operation)) continue
    const view = auth.crd_views.find((entry) => entry.operation === operation)
    const row = viewRow(operation === "search" ? "Search CRD cost" : "Fetch CRD cost", view)
    if (row !== null) rows.push(row)
  }
  return rows
}

/** Known aggregate funds of one native pool, shown once under its human name. */
function poolRows(pool: NativePool | null): DetailRow[] {
  if (pool === null) return []
  const remaining = nativeText(pool.remaining, pool.native_unit)
  const allowance = nativeText(pool.allowance, pool.native_unit)
  if (remaining === null && allowance === null) return []
  const parts: string[] = []
  if (remaining !== null) parts.push(remaining + " left")
  if (allowance !== null) parts.push("of " + allowance)
  const name = poolName(pool.pool_id)
  const value = name === "" ? parts.join(" ") : name + ": " + parts.join(" ")
  return [{ kind: amountKind(pool.native_unit), label: "Aggregate pool", value }]
}

function rateWindowText(window: LimitRateWindow): string | null {
  const limit = known(window.limit)
  const remaining = known(window.remaining)
  if (limit === null && remaining === null) return null
  const label = WINDOW_TEXT[window.window] ?? "window"
  const parts: string[] = []
  if (limit !== null) {
    const scope = known(window.scope)
    const suffix = scope === null ? "" : " (" + scope + ")"
    parts.push(limit + " " + window.unit + " per " + label + suffix)
  }
  if (remaining !== null) parts.push(remaining + " left")
  return parts.join(", ")
}

/** Second and minute rate windows stay text; the hour and day windows are bars. */
function rateRows(detail: ProviderLimitDetail | null): DetailRow[] {
  if (detail === null) return []
  return detail.rate_windows
    .filter((window) => TEXT_WINDOWS.includes(window.window))
    .map((window) => ({ kind: "plain" as RowKind, label: "Rate window", value: rateWindowText(window) }))
    .filter((row): row is DetailRow => row.value !== null)
}

/** Group the rows by value family: credit units, then plain facts, then USD amounts. */
function groupRows(rows: DetailRow[]): DetailRow[] {
  return [...rows].sort((left, right) => ROW_ORDER.indexOf(left.kind) - ROW_ORDER.indexOf(right.kind))
}

/**
 * Collapsed vendor detail of one provider rail.
 *
 * Native and USD amounts keep their vendor precision; only credit-unit values
 * use the one-digit display rule. Every USD amount sits in one block at the end
 * and every credit-unit amount sits in one block above it, so the two families
 * never alternate. An absent or unknown field yields no row, so no placeholder
 * and no invented zero ever appears here.
 */
export function ProviderLimitsDetail({ providerName, auth }: ProviderLimitsDetailProps): ReactNode {
  const detail = auth.detail
  const rows = groupRows([
    ...detailRows(detail, planText(detail, auth)),
    ...grantRows(auth.grants, auth),
    ...viewRows(auth),
    ...poolRows(auth.aggregate_pool),
    ...rateRows(detail),
  ])
  const splitNote = detail === null ? null : known(detail.crd_split_note)
  const href = safeHref(detail === null ? null : detail.usage_url)

  return (
    <div className="space-y-2 text-[12px]">
      {rows.length > 0 && (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
          {rows.map((row, index) => (
            <div key={row.label + "-" + index} className="flex items-baseline justify-between gap-3">
              <dt className="text-[var(--muted)]">{row.label}</dt>
              <dd className="tnum text-right text-[var(--text)]">{row.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {splitNote !== null && <p className="text-[var(--muted)]">{splitNote}</p>}
      {href !== null && (
        <a
          className="text-[var(--signal)] underline"
          href={href}
          target="_blank"
          rel="noreferrer noopener"
        >
          {providerName} usage page
        </a>
      )}
    </div>
  )
}
