import type { ReactNode } from "react"
import type {
  CRDGrantsSummary,
  ProviderAuthLimits,
  ProviderLimitDetail,
} from "@/domains/dashboard"
import { dollarText, resetRuleText } from "../model/crdDisplay"
import { operationAvailable } from "../model/crdCardModel"
import type { TavilyDisplayAdapter } from "../model/tavilyCredits"
import { formatTavilyPopoverAmount } from "../model/tavilyCredits"
import { SPEND_CAP } from "../model/quotaLabels"
import { dateText } from "../model/timeText"
import { multiplyDecimal } from "../model/manualQuotaMath"

export interface ProviderLimitsDetailProps {
  providerName: string
  auth: ProviderAuthLimits
  /** The popover keeps each detail row on its own line at narrow widths. */
  layout?: "default" | "popover"
  /**
   * The native display inputs of one Tavily rail: with a price profile, the
   * local grant caps state themselves in Credits. Other providers keep CRD.
   */
  nativeDisplay?: TavilyDisplayAdapter
}

/** Value family of one row: the credit-unit block comes first and the USD block goes last. */
type RowKind = "crd" | "plain" | "usd"
const ROW_ORDER: RowKind[] = ["crd", "plain", "usd"]

interface DetailRow {
  kind: RowKind
  label: string
  value: string
}

const EDGE = "space-y-2 border-t border-[var(--border-subtle)] pt-3 text-[12px]"

/** Known text only: an absent, empty, or unknown value yields no row. */
function known(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "" || text.toLowerCase() === "unknown" || text === "n/a") return null
  return text
}

function push(rows: DetailRow[], kind: RowKind, label: string, value: string | null): void {
  if (value !== null) rows.push({ kind, label, value })
}

/** Only a known reset rule becomes a row; an unknown rule stays absent. */
function resetText(detail: ProviderLimitDetail | null): string | null {
  if (detail === null || detail.reset_rule === "unknown") return null
  return resetRuleText(detail.reset_rule, detail.reset_at)
}

/**
 * The vendor rows that no other surface states.
 *
 * The credit fraction of the card states the remaining amount and the total.
 * The info control states the call cost, the call count, the rate limit, the
 * last sync time, and the usage page. This block states the vendor spend and
 * the reset only, so no amount and no time appears twice.
 */
function detailRows(detail: ProviderLimitDetail | null, native: boolean = false): DetailRow[] {
  const rows: DetailRow[] = []
  if (detail === null) return rows
  const spend = known(detail.actual_spend_usd)
  if (spend !== null) {
    const value = native ? formatTavilyPopoverAmount(spend, "usd") : spend
    push(rows, "usd", "Vendor-reported USD spend", value)
  }
  push(rows, "plain", "Reset", resetText(detail))
  return rows
}

/** The local budget always states USD, including providers with native credits. */
function grantText(granted: string, consumed: string): string {
  return dollarText(multiplyDecimal(granted, "0.001") ?? "0") + " set, "
    + dollarText(multiplyDecimal(consumed, "0.001") ?? "0") + " used"
}

/** Spend cap facts of the supported operations only. */
function grantRows(
  grants: CRDGrantsSummary | null,
  auth: ProviderAuthLimits,
  native: boolean,
): DetailRow[] {
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
    const operation = native ? "Extract" : "Fetch"
    push(rows, "crd", operation + " " + SPEND_CAP.toLowerCase(), grantText(grants.fetch_granted_crd, grants.fetch_consumed_crd))
  }
  return rows
}

/** Group the rows by value family: credit units, then plain facts, then USD amounts. */
function groupRows(rows: DetailRow[]): DetailRow[] {
  return [...rows].sort((left, right) => ROW_ORDER.indexOf(left.kind) - ROW_ORDER.indexOf(right.kind))
}

/**
 * The remaining vendor detail of one provider rail.
 *
 * Native and USD amounts keep their vendor precision; only credit-unit values
 * use the one-digit display rule. An absent or unknown field yields no row, so
 * no placeholder and no invented zero ever appears here. A rail without a row
 * yields no block at all, so the info control holds no empty divider.
 */
export function ProviderLimitsDetail(props: ProviderLimitsDetailProps): ReactNode {
  const { providerName, auth, nativeDisplay, layout = "default" } = props
  const native = nativeDisplay !== undefined
  const detail = auth.detail
  const rows = groupRows([...detailRows(detail, native), ...grantRows(auth.grants, auth, native)])
  const splitNote = detail === null ? null : known(detail.crd_split_note)
  if (rows.length === 0 && splitNote === null) return null

  return (
    <div role="group" aria-label={providerName + " vendor detail"} className={EDGE}>
      {rows.length > 0 && (
        <dl
          className={
            layout === "popover"
              ? "grid grid-cols-1 gap-y-1"
              : "grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2"
          }
        >
          {rows.map((row, index) => (
            <div key={row.label + "-" + index} className="flex items-baseline justify-between gap-3">
              <dt className="min-w-0 text-[var(--muted)]">{row.label}</dt>
              <dd className="min-w-0 flex-1 break-words tnum text-right text-[var(--text)]">{row.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {splitNote !== null && <p className="text-[var(--muted)]">{splitNote}</p>}
    </div>
  )
}
