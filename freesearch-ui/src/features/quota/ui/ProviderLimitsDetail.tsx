import type { ReactNode } from "react"
import type {
  CRDGrantsSummary,
  CRDView,
  LimitRateWindow,
  NativePool,
  ProviderAuthLimits,
  ProviderLimitDetail,
} from "@/domains/dashboard"
import { formatCRDAmount, resetRuleText } from "../model/crdDisplay"
import { operationAvailable } from "../model/crdCardModel"

export interface ProviderLimitsDetailProps {
  providerName: string
  auth: ProviderAuthLimits
}

interface DetailRow {
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

function nativeText(amountValue: string | null, unit: string | null): string | null {
  const text = known(amountValue)
  if (text === null) return null
  const label = known(unit)
  return label === null ? text : text + " " + label
}

/** Only http and https links become anchors; any other text stays plain. */
function safeHref(url: string | null): string | null {
  if (url === null) return null
  return /^https?:\/\//i.test(url) ? url : null
}

function push(rows: DetailRow[], label: string, value: string | null): void {
  if (value !== null) rows.push({ label, value })
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
  push(rows, "Plan", plan)
  push(rows, "Native balance", nativeText(detail.native_balance, detail.native_unit))
  push(rows, "Native allowance", nativeText(detail.native_allowance, detail.native_unit))
  push(rows, "USD per call", known(detail.usd_per_call))
  push(rows, "Vendor-reported USD spend", known(detail.actual_spend_usd))
  push(rows, "Reset", resetText(detail))
  push(rows, "Last sync", known(detail.last_sync_at))
  return rows
}

function grantText(granted: string, consumed: string): string {
  return formatCRDAmount(granted) + " granted, " + formatCRDAmount(consumed) + " used"
}

/** Grant facts of the supported operations only. */
function grantRows(grants: CRDGrantsSummary | null, auth: ProviderAuthLimits): DetailRow[] {
  const rows: DetailRow[] = []
  if (grants === null) return rows
  const start = known(grants.period_start)
  const end = known(grants.period_end)
  push(rows, "Grant period", start === null || end === null ? null : start + " to " + end)
  if (operationAvailable(auth, "search")) {
    push(rows, "Search grant", grantText(grants.search_granted_crd, grants.search_consumed_crd))
  }
  if (operationAvailable(auth, "fetch")) {
    push(rows, "Fetch grant", grantText(grants.fetch_granted_crd, grants.fetch_consumed_crd))
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
  return parts.length === 0 ? null : { label, value: parts.join(", ") }
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

/** Known aggregate funds of one native pool, shown once. */
function poolRows(pool: NativePool | null): DetailRow[] {
  if (pool === null) return []
  const remaining = nativeText(pool.remaining, pool.native_unit)
  const allowance = nativeText(pool.allowance, pool.native_unit)
  if (remaining === null && allowance === null) return []
  const parts: string[] = []
  if (remaining !== null) parts.push(remaining + " left")
  if (allowance !== null) parts.push("of " + allowance)
  const id = known(pool.pool_id)
  const value = id === null ? parts.join(" ") : id + ": " + parts.join(" ")
  return [{ label: "Aggregate pool", value }]
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
    .map((window) => ({ label: "Rate window", value: rateWindowText(window) }))
    .filter((row): row is DetailRow => row.value !== null)
}

/**
 * Collapsed vendor detail of one provider rail.
 *
 * Native and USD amounts keep their vendor precision; only credit-unit values
 * use the one-digit display rule. An absent or unknown field yields no row, so
 * no placeholder and no invented zero ever appears here.
 */
export function ProviderLimitsDetail({ providerName, auth }: ProviderLimitsDetailProps): ReactNode {
  const detail = auth.detail
  const rows = [
    ...detailRows(detail, planText(detail, auth)),
    ...grantRows(auth.grants, auth),
    ...viewRows(auth),
    ...poolRows(auth.aggregate_pool),
    ...rateRows(detail),
  ]
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
