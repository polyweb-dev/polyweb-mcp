import type { ReactNode } from "react"
import type {
  CRDConversionProfile,
  CRDGrantsSummary,
  ProviderAuthLimits,
  ProviderLimitDetail,
} from "@/domains/dashboard"
import { formatCRDAmount, resetRuleText } from "../model/crdDisplay"
import { operationAvailable } from "../model/crdCardModel"
import type { TavilyDisplayAdapter } from "../model/tavilyCredits"
import { tavilyCRDToCredits, formatCreditAmount } from "../model/tavilyCredits"
import { SPEND_CAP } from "../model/quotaLabels"
import { dateText } from "../model/timeText"

export interface ProviderLimitsDetailProps {
  providerName: string
  auth: ProviderAuthLimits
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
function detailRows(detail: ProviderLimitDetail | null): DetailRow[] {
  const rows: DetailRow[] = []
  if (detail === null) return rows
  push(rows, "usd", "Vendor-reported USD spend", known(detail.actual_spend_usd))
  push(rows, "plain", "Reset", resetText(detail))
  return rows
}

function grantText(granted: string, consumed: string): string {
  return formatCRDAmount(granted) + " set, " + formatCRDAmount(consumed) + " used"
}

/**
 * The grant text of one rail: with a native price profile the CRD amounts
 * convert into Credits at the display boundary, and a failed conversion keeps
 * the stored CRD text. The wire values stay untouched.
 */
function grantTextNative(
  granted: string,
  consumed: string,
  profile: CRDConversionProfile | null,
): string {
  if (profile === null) return grantText(granted, consumed)
  const grantedCredits = tavilyCRDToCredits(granted, profile)
  const usedCredits = tavilyCRDToCredits(consumed, profile)
  if (grantedCredits === null || usedCredits === null) return grantText(granted, consumed)
  return formatCreditAmount(grantedCredits) + " set, " + formatCreditAmount(usedCredits) + " used"
}

/** Spend cap facts of the supported operations only. */
function grantRows(
  grants: CRDGrantsSummary | null,
  auth: ProviderAuthLimits,
  profile: CRDConversionProfile | null,
  native: boolean,
): DetailRow[] {
  const rows: DetailRow[] = []
  if (grants === null) return rows
  const start = known(grants.period_start)
  const end = known(grants.period_end)
  const period = start === null || end === null ? null : dateText(start) + " to " + dateText(end)
  push(rows, "plain", SPEND_CAP + " period", period)
  if (operationAvailable(auth, "search")) {
    push(rows, "crd", "Search " + SPEND_CAP.toLowerCase(), grantTextNative(grants.search_granted_crd, grants.search_consumed_crd, profile))
  }
  if (operationAvailable(auth, "fetch")) {
    const operation = native ? "Extract" : "Fetch"
    push(rows, "crd", operation + " " + SPEND_CAP.toLowerCase(), grantTextNative(grants.fetch_granted_crd, grants.fetch_consumed_crd, profile))
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
  const { providerName, auth, nativeDisplay } = props
  const profile = nativeDisplay?.profile ?? null
  const native = nativeDisplay !== undefined
  const detail = auth.detail
  const rows = groupRows([...detailRows(detail), ...grantRows(auth.grants, auth, profile, native)])
  const splitNote = detail === null ? null : known(detail.crd_split_note)
  if (rows.length === 0 && splitNote === null) return null

  return (
    <div role="group" aria-label={providerName + " vendor detail"} className={EDGE}>
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
    </div>
  )
}
