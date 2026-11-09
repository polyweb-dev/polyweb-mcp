import type { ProviderAuthLimits } from "@/domains/dashboard"
import type { ProviderInfoFact } from "./providerInfoTypes"
import { callsText } from "./usdDisplay"
import { multiplyDecimal } from "./manualQuotaMath"
import { groupDigits } from "./numberText"
import { formatTavilyPopoverAmount } from "./tavilyCredits"

function known(value: string | null | undefined): string | null {
  if (value == null) return null
  const text = value.trim()
  return text === "" || text === "unknown" || text === "n/a" ? null : text
}

/** The credit word of one native amount: "1" reads singular, any other plural. */
function creditWord(amount: string | null): string {
  if (amount === null) return ""
  return amount === "1" ? "1 Tavily credit" : groupDigits(amount) + " Tavily credits"
}

/** The URL batch of one Tavily extract price. */
const EXTRACT_BATCH_URLS = "5"

/**
 * The native Tavily Credits cost of one Tavily operation.
 *
 * Search bills 1 Credit per basic call and 2 per advanced call; extract bills
 * 1 or 2 Credits per five successful URLs. The amounts come from the payload
 * budget, so an absent budget yields no row and no USD appears outside the
 * disclosure. The shown amounts are whole Tavily Credits, floored without
 * binary float; the extract amount multiplies by five before display.
 */
export function nativeCostFact(
  auth: ProviderAuthLimits,
  operation: "search" | "fetch",
): ProviderInfoFact | null {
  const record = operation === "search" ? auth.search : auth.fetch
  const nativeCost = known(record?.budget?.standard_native_cost)
  if (nativeCost === null) return null
  const isSearch = operation === "search"
  const batchRaw = isSearch ? nativeCost : multiplyDecimal(nativeCost, EXTRACT_BATCH_URLS)
  if (batchRaw === null) return null
  const batch = formatTavilyPopoverAmount(batchRaw, "native")
  const advancedBatchRaw = multiplyDecimal(batchRaw, "2")
  const advancedBatch = advancedBatchRaw === null ? null : formatTavilyPopoverAmount(advancedBatchRaw, "native")
  if (batch === null || advancedBatch === null) return null
  return {
    label: isSearch ? "Search cost" : "Extract cost",
    value: creditWord(batch) + (isSearch ? "" : " per " + EXTRACT_BATCH_URLS + " URLs"),
    note: "(advanced: " + creditWord(advancedBatch) + ")",
  }
}

/** The label of the shared Tavily search and fetch minute ceiling. */
const TAVILY_RATE_LABEL = "Search and fetch rate limit"

/** The Tavily minute ceiling, with its current headroom when known. */
function tavilyRateValue(remaining: string | null, limit: string): string {
  let amount: string
  if (remaining === null) amount = "Limit " + groupDigits(limit)
  else if (remaining === limit) amount = groupDigits(limit)
  else amount = groupDigits(remaining) + "/" + groupDigits(limit)
  return amount + " requests per minute"
}

/** The combined Tavily search and fetch rate row with a confirmed ceiling. */
function tavilyCombinedRateFact(
  auth: ProviderAuthLimits,
  rateLimitOverride?: string,
): ProviderInfoFact | null {
  const { remaining, limit } = minuteCounts(auth)
  const overrideRaw = known(rateLimitOverride ?? null)
  const overrideCeiling = overrideRaw === null ? null : callsText(overrideRaw)
  if (overrideCeiling === null && (auth.auth_mode === "keyless" || remaining === null)) return null
  const ceiling = overrideCeiling ?? limit
  if (ceiling === null) return null
  return { label: TAVILY_RATE_LABEL, value: tavilyRateValue(ceiling === limit ? remaining : null, ceiling), note: null }
}

function minuteCounts(auth: ProviderAuthLimits): { remaining: string | null; limit: string | null } {
  const minute = auth.detail?.rate_windows.find((entry) => entry.window === "1m")
  if (minute?.unit !== "requests") return { remaining: null, limit: null }
  return { remaining: wholeCount(minute.remaining), limit: wholeCount(minute.limit) }
}

function wholeCount(value: string | null | undefined): string | null {
  const raw = known(value)
  return raw === null ? null : callsText(raw)
}

/** The combined Tavily rate row and the active retry delay of one Tavily rail. */
export function tavilyRateFacts(auth: ProviderAuthLimits, rateLimitOverride?: string): ProviderInfoFact[] {
  const facts: ProviderInfoFact[] = []
  const combined = tavilyCombinedRateFact(auth, rateLimitOverride)
  if (combined !== null) facts.push(combined)
  const delay = auth.detail?.retry_after_seconds
  if (typeof delay === "number" && Number.isFinite(delay)) {
    facts.push({ label: "Retry after", value: Math.ceil(delay) + " s", note: null })
  }
  return facts
}

