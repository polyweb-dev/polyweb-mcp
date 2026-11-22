import type { ProjectUsageTotal } from "@/domains/usage"
import { formatCallCost, formatCostTotal, providerIdentity } from "@/domains/providers"
import type { ProjectOrder } from "@/domains/routing"

/** Metered amounts of one row, one field per unit kind; null when none was recorded. */
export interface UsageAmounts {
  calls: number
  usd: number | null
  requests: number | null
  credits: number | null
  /** Units recorded before unit kinds existed; never merged into a known kind. */
  other: number | null
  /** At least one call ran on a free (keyless) allowance. */
  free: boolean
  unreportedCost: boolean
  /** Part of the dollar amount is estimated from the catalog price. */
  estimated: boolean
}

interface UsageTotalsRow extends UsageAmounts {
  key: string
  provider: string
  operation: string
}

export type UsageAmountColumn = "usd" | "requests" | "credits" | "other"

interface UsageTotalsView {
  rows: UsageTotalsRow[]
  total: UsageAmounts
  /** Only the unit columns some row uses, in a fixed order. */
  columns: UsageAmountColumn[]
}

const COLUMN_ORDER: readonly UsageAmountColumn[] = ["usd", "requests", "credits", "other"]
const OPERATION_ORDER: Readonly<Record<string, number>> = { search: 0, fetch: 1 }

function emptyAmounts(): UsageAmounts {
  return {
    calls: 0, usd: null, requests: null, credits: null, other: null,
    free: false, unreportedCost: false, estimated: false,
  }
}

function add(current: number | null, units: number): number {
  return (current ?? 0) + units
}

/** Add the USD cost of one ledger total; a free row is never counted as unpriced. */
function accumulateCost(amounts: UsageAmounts, total: ProjectUsageTotal, knownFree: boolean): void {
  const free = knownFree || total.unitKind === "FREE"
  if (free || (total.costUsd === 0 && total.unpricedCount === 0)) amounts.free = true
  if (total.unpricedCount > 0 && !free) amounts.unreportedCost = true
  if (total.costUsd === null) return
  // Ledger costs arrive as numbers, so remove binary addition noise from every running sum.
  amounts.usd = Number(add(amounts.usd, total.costUsd).toPrecision(15))
  if (total.costEstimated) amounts.estimated = true
}

/** Add one ledger total into a row: calls always, units only into their own kind. */
function accumulate(amounts: UsageAmounts, total: ProjectUsageTotal, knownFree: boolean): void {
  amounts.calls += total.eventCount
  accumulateCost(amounts, total, knownFree)
  switch (total.unitKind) {
    case "USD":
    case "FREE":
      break
    case "REQUEST":
      amounts.requests = add(amounts.requests, total.totalUnits)
      break
    case "CREDIT":
      amounts.credits = add(amounts.credits, total.totalUnits)
      break
    default:
      amounts.other = add(amounts.other, total.totalUnits)
  }
}

/** A cost column also shows "Free" for keyless rows, so FREE counts as using it. */
function usesColumn(amounts: UsageAmounts, column: UsageAmountColumn): boolean {
  if (column === "usd") return amounts.calls > 0 || amounts.usd !== null || amounts.free
  return amounts[column] !== null
}

/**
 * One row per provider and operation with every unit kind in its own column,
 * plus the column totals. Kinds are never summed together, so dollars,
 * requests and credits each stay comparable down their own column.
 */
export function usageTotalsView(totals: readonly ProjectUsageTotal[], order?: ProjectOrder): UsageTotalsView {
  const byKey = new Map<string, UsageTotalsRow>()
  const total = emptyAmounts()
  for (const entry of totals) {
    const key = `${entry.provider}:${entry.operation}`
    const row = byKey.get(key) ?? { key, provider: entry.provider, operation: entry.operation, ...emptyAmounts() }
    const operation = entry.operation === "search" || entry.operation === "fetch" ? entry.operation : null
    const price = operation === null ? undefined : order?.[operation].providers.find(
      (provider) => providerIdentity(provider.provider).id === providerIdentity(entry.provider).id
    )
    const knownFree = price !== undefined && (price.keyless || (price.callCostUsd !== null && Number(price.callCostUsd) === 0))
    accumulate(row, entry, knownFree)
    accumulate(total, entry, knownFree)
    byKey.set(key, row)
  }
  return {
    rows: [...byKey.values()].sort((a, b) => (OPERATION_ORDER[a.operation] ?? 2) - (OPERATION_ORDER[b.operation] ?? 2)),
    total,
    columns: COLUMN_ORDER.filter((column) =>
      usesColumn(total, column) &&
      (column !== "requests" || [...byKey.values()].some((row) => row.requests !== null && row.requests !== row.calls))
    ),
  }
}

const AMOUNT_FORMAT: Intl.NumberFormatOptions = { maximumFractionDigits: 4 }

/** One unit cell: its amount, and whether that amount is partly estimated. */
interface UsageAmount {
  text: string
  estimated: boolean
}

/** The cell amount of one unit column; a dash when the row recorded none. */
export function usageAmount(amounts: UsageAmounts, column: UsageAmountColumn): UsageAmount {
  const value = amounts[column]
  if (column === "usd" && (value === null || value === 0) && amounts.free && !amounts.unreportedCost) {
    return { text: formatCallCost(0), estimated: false }
  }
  if (value === null) return { text: "—", estimated: false }
  if (column !== "usd") return { text: value.toLocaleString("en-US", AMOUNT_FORMAT), estimated: false }
  // Ledger values arrive as numbers, so remove binary addition noise before display.
  return { text: formatCostTotal(Number(value.toPrecision(15))), estimated: amounts.estimated }
}

/** The visible cell text of one unit column; "~" marks an estimated amount. */
export function usageAmountText(amounts: UsageAmounts, column: UsageAmountColumn): string {
  const { text, estimated } = usageAmount(amounts, column)
  return estimated ? `~${text}` : text
}

/** The tooltip of a cell whose dollar amount is partly estimated. */
export function usageAmountTitle(amounts: UsageAmounts, column: UsageAmountColumn): string | undefined {
  return usageAmount(amounts, column).estimated ? "Estimated from the catalog price" : undefined
}

export const USAGE_COLUMN_LABELS: Readonly<Record<UsageAmountColumn, string>> = {
  usd: "Cost",
  requests: "Billed requests",
  credits: "Provider credits",
  other: "Other units",
}

/** What each unit column counts, shown as the header tooltip. */
export const USAGE_COLUMN_HINTS: Readonly<Record<UsageAmountColumn, string>> = {
  usd: "Provider charges in US dollars. ~ marks an estimate from the catalog price; totals include known costs only",
  requests: "Calls counted against a provider's request allowance",
  credits: "Credits the provider deducted, in its own unit",
  other: "Units recorded before unit types were tracked",
}
