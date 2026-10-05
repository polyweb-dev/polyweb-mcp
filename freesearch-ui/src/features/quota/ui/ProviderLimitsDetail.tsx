import type { ReactNode } from "react"
import type {
  CRDView,
  CRDGrantsSummary,
  LimitRateWindow,
  NativePool,
  ProviderAuthLimits,
  ProviderLimitDetail,
  QuotaConfidence,
} from "@/domains/dashboard"
import type { CRDConfidence } from "@/domains/dashboard"
import { formatCRDAmount, resetRuleText } from "../model/crdDisplay"
import { QuotaSource } from "./QuotaSource"

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
  unknown: "window",
}

function orDash(value: string | null): string {
  return value === null || value.trim() === "" ? "—" : value
}

function nativeText(amountValue: string | null, unit: string | null): string {
  if (amountValue === null) return "—"
  return unit === null ? amountValue : amountValue + " " + unit
}

/** Only http and https links become anchors; any other text stays plain. */
function safeHref(url: string | null): string | null {
  if (url === null) return null
  return /^https?:\/\//i.test(url) ? url : null
}

function confidence(value: CRDConfidence): QuotaConfidence | null {
  return value === "unknown" ? null : value
}

function planText(detail: ProviderLimitDetail | null, auth: ProviderAuthLimits): string {
  const fromDetail = detail === null ? null : detail.plan_name
  if (fromDetail !== null) return fromDetail
  if (auth.search === null) return "—"
  return orDash(auth.search.plan_name)
}

function detailRows(detail: ProviderLimitDetail | null, plan: string): DetailRow[] {
  if (detail === null) {
    return [{ label: "Vendor detail", value: "Not reported" }]
  }
  return [
    { label: "Plan", value: plan },
    { label: "Native balance", value: nativeText(detail.native_balance, detail.native_unit) },
    { label: "Native allowance", value: nativeText(detail.native_allowance, detail.native_unit) },
    { label: "USD per call", value: orDash(detail.usd_per_call) },
    { label: "Actual USD spend", value: orDash(detail.actual_spend_usd) },
    { label: "Reset", value: resetRuleText(detail.reset_rule, detail.reset_at) },
    { label: "Price version", value: orDash(detail.price_version) },
    { label: "Last sync", value: orDash(detail.last_sync_at) },
  ]
}

function grantRows(grants: CRDGrantsSummary | null): DetailRow[] {
  if (grants === null) return []
  const search = formatCRDAmount(grants.search_granted_crd) + " granted, "
    + formatCRDAmount(grants.search_consumed_crd) + " used"
  const fetch = formatCRDAmount(grants.fetch_granted_crd) + " granted, "
    + formatCRDAmount(grants.fetch_consumed_crd) + " used"
  return [
    { label: "Grant period", value: grants.period_start + " to " + grants.period_end },
    { label: "Search grant", value: search },
    { label: "Fetch grant", value: fetch },
  ]
}

function viewRow(label: string, view: CRDView | undefined): DetailRow | null {
  if (view === undefined) return null
  const cost = view.request_cost_crd === null ? "—" : formatCRDAmount(view.request_cost_crd)
  const calls = view.possible_standard_calls === null ? "—" : view.possible_standard_calls
  return { label, value: cost + " per standard call, " + calls + " calls left" }
}

function viewRows(views: CRDView[]): DetailRow[] {
  const rows: DetailRow[] = []
  const search = viewRow("Search CRD cost", views.find((view) => view.operation === "search"))
  if (search !== null) rows.push(search)
  const fetch = viewRow("Fetch CRD cost", views.find((view) => view.operation === "fetch"))
  if (fetch !== null) rows.push(fetch)
  return rows
}

function poolRows(pool: NativePool | null): DetailRow[] {
  if (pool === null) return []
  const value = pool.pool_id + ": " + nativeText(pool.remaining, pool.native_unit)
  return [{ label: "Aggregate pool", value }]
}

function rateWindowText(window: LimitRateWindow): string {
  const label = WINDOW_TEXT[window.window] ?? "window"
  const limit = window.limit + " " + window.unit + " per " + label + " (" + window.scope + ")"
  return window.remaining === null ? limit : limit + ", " + window.remaining + " left"
}

/**
 * Collapsed vendor detail of one provider rail.
 *
 * Native and USD amounts keep their vendor precision; only credit-unit values
 * use the one-digit display rule. Rate windows of every length appear here as
 * text, including the second and minute windows that never become bars.
 */
export function ProviderLimitsDetail({ providerName, auth }: ProviderLimitsDetailProps): ReactNode {
  const detail = auth.detail
  const rows = [
    ...detailRows(detail, planText(detail, auth)),
    ...grantRows(auth.grants),
    ...viewRows(auth.crd_views),
    ...poolRows(auth.aggregate_pool),
  ]
  const source = detail === null ? null : confidence(detail.confidence)
  const splitNote = detail === null ? null : detail.crd_split_note
  const windows = detail === null ? [] : detail.rate_windows
  const stale = detail !== null && detail.stale
  const href = safeHref(detail === null ? null : detail.usage_url)

  return (
    <div className="space-y-2 text-[12px]">
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-3">
            <dt className="text-[var(--muted)]">{row.label}</dt>
            <dd className="tnum text-right text-[var(--text)]">{row.value}</dd>
          </div>
        ))}
        <div className="flex items-baseline justify-between gap-3">
          <dt className="text-[var(--muted)]">Source</dt>
          <dd className="tnum text-right text-[var(--text)]">
            <QuotaSource confidence={source} />
          </dd>
        </div>
      </dl>
      {!auth.tier_split_known && (
        <p className="text-[var(--muted)]">
          Tier split unavailable. The vendor reports one aggregate balance, so the free and paid
          bars stay unknown and the aggregate pool appears here once.
        </p>
      )}
      {splitNote !== null && <p className="text-[var(--muted)]">{splitNote}</p>}
      {windows.length > 0 && (
        <ul className="space-y-0.5 text-[var(--muted)]">
          {windows.map((window) => (
            <li key={window.bucket_id + "-" + window.window + "-" + window.unit}>
              Rate window: {rateWindowText(window)}
            </li>
          ))}
        </ul>
      )}
      {stale && (
        <p className="text-[var(--muted)]">
          The vendor balance is stale; the last sync did not confirm it.
        </p>
      )}
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
