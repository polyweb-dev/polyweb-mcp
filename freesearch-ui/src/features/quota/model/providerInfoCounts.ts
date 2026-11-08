import type { CRDResetRule, CRDView, ProviderAuthLimits } from "@/domains/dashboard"
import type { ProviderInfoFact } from "./providerInfoTypes"
import { callsText } from "./crdDisplay"
import { parseDecimal } from "./manualQuotaMath"
import { groupDigits } from "./numberText"

const UNKNOWN_TEXT = "unknown"

function known(value: string | null | undefined): string | null {
  if (value == null) return null
  const text = value.trim()
  return text === "" || text === "unknown" || text === "n/a" ? null : text
}

/** The reset rule gives the period of one call count. */
const COUNT_PERIOD: Record<CRDResetRule, string | null> = {
  monthly_first: "month",
  vendor_period: "vendor period",
  daily_vendor: "day",
  daily_estimate: "day",
  never: null,
  unknown: null,
}

/** The count row name of one operation, with the Tavily extract view name. */
const COUNT_LABEL = { search: "Searches left", fetch: "Fetches left" }

/** Exact floor of one non-negative division, or null when either side is unusable. */
function floorDivToInt(numerator: string, denominator: string): string | null {
  const top = parseDecimal(numerator.trim())
  const bottom = parseDecimal(denominator.trim())
  if (top === null || bottom === null || bottom.int === 0n) return null
  const num = top.int * 10n ** BigInt(bottom.scale)
  const den = bottom.int * 10n ** BigInt(top.scale)
  if (den <= 0n || num < 0n) return null
  return (num / den).toString()
}

/**
 * Total You.com searches left: the daily free pool plus the credit-derived
 * searches from the shared USD balance (frontend display-only).
 *
 * The backend search view holds only the covering daily pool (100/day) while
 * it still covers one request, so its possible_standard_calls reads 100 even
 * when the credit balance covers thousands more (39904 from $199.52 at
 * $0.005/search). The fetch view already projects the same balance in
 * fetch units (199520 at 1 CRD each), so the credit searches come from
 * floor(fetch remaining CRD / search CRD cost) without a second conversion.
 * Null unless the search view is the daily pool (a different shared pool
 * than the aggregate) with both CRD amounts known, so a pool-projected
 * search view never double-counts and no reset is invented.
 */
function youcomSearchTotal(auth: ProviderAuthLimits, searchView: CRDView | undefined, dailyRaw: string): string | null {
  const daily = callsText(dailyRaw)
  const extra = creditSearches(auth, searchView)
  if (daily === null || extra === null) return null
  try {
    return (BigInt(daily) + BigInt(extra)).toString()
  } catch {
    return null
  }
}

function creditSearches(auth: ProviderAuthLimits, searchView: CRDView | undefined): string | null {
  const poolId = auth.aggregate_pool?.pool_id ?? null
  if (poolId === null) return null
  if (searchView?.shared_pool_id === poolId) return null
  const fetchView = auth.crd_views.find((entry) => entry.operation === "fetch")
  const fetchRemaining = known(fetchView?.remaining_crd)
  const searchCost = known(searchView?.request_cost_crd)
  if (fetchRemaining === null || searchCost === null) return null
  return floorDivToInt(fetchRemaining, searchCost)
}

/** The whole standard calls left of one operation, with the reset period. */
export function countFact(
  auth: ProviderAuthLimits,
  operation: "search" | "fetch",
  providerId: string | undefined,
  wholeRequests: boolean = false,
): ProviderInfoFact | null {
  const view = auth.crd_views.find((entry) => entry.operation === operation)
  const raw = known(view?.possible_standard_calls)
  if (raw === null) return null
  // You.com search total (display-only): daily 100 plus credit-derived
  // searches from the same balance the Fetches left row already projects.
  // Every other provider keeps its verbatim view count.
  const effective = effectiveCount({ providerId, operation, auth, view, raw })
  const calls =
    wholeRequests || ["tavily", "firecrawl", "exa"].includes(providerId ?? "")
      ? callsText(effective)
      : effective
  if (calls === null) return null
  const period = COUNT_PERIOD[auth.detail?.reset_rule ?? UNKNOWN_TEXT]
  return {
    label: COUNT_LABEL[operation],
    value: groupDigits(calls),
    note: period === null ? null : "/ " + period,
  }
}

function effectiveCount(input: { providerId: string | undefined; operation: string; auth: ProviderAuthLimits; view: CRDView | undefined; raw: string }): string {
  if (input.providerId === "youcom" && input.operation === "search") return youcomSearchTotal(input.auth, input.view, input.raw) ?? input.raw
  return input.raw
}

