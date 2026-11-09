import type { ProjectUsageTotal } from "@/domains/usage"
import { providerIdentity } from "@/domains/providers"
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

function emptyAmounts(): UsageAmounts {
  return { calls: 0, usd: null, requests: null, credits: null, other: null, free: false, unreportedCost: false }
}

function add(current: number | null, units: number): number {
  return (current ?? 0) + units
}

/** Add one ledger total into a row: calls always, units only into their own kind. */
function accumulate(amounts: UsageAmounts, total: ProjectUsageTotal, knownFree: boolean): void {
  amounts.calls += total.eventCount
  if (knownFree || total.unitKind === "FREE" || (total.unitKind === "USD" && total.totalUnits === 0)) {
    amounts.free = true
  }
  if (total.unitKind !== "USD" && total.unitKind !== "FREE" && !knownFree) amounts.unreportedCost = true
  switch (total.unitKind) {
    case "USD":
      amounts.usd = add(amounts.usd, total.totalUnits)
      break
    case "REQUEST":
      amounts.requests = add(amounts.requests, total.totalUnits)
      break
    case "CREDIT":
      amounts.credits = add(amounts.credits, total.totalUnits)
      break
    case "FREE":
      amounts.free = true
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
    rows: [...byKey.values()],
    total,
    columns: COLUMN_ORDER.filter((column) =>
      usesColumn(total, column) &&
      (column !== "requests" || [...byKey.values()].some((row) => row.requests !== null && row.requests !== row.calls))
    ),
  }
}

const AMOUNT_FORMAT: Intl.NumberFormatOptions = { maximumFractionDigits: 4 }
/** Dollars like Overview: `$0.035`, `$12.50`. */
const USD_FORMAT: Intl.NumberFormatOptions = {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
}

/** The cell text of one unit column; a dash when the row recorded none. */
export function usageAmountText(amounts: UsageAmounts, column: UsageAmountColumn): string {
  const value = amounts[column]
  if (column === "usd" && (value === null || value === 0)) {
    if (amounts.free && !amounts.unreportedCost) return "Free"
    if (value === null) return "Not reported"
  }
  if (value === null) return "—"
  return value.toLocaleString("en-US", column === "usd" ? USD_FORMAT : AMOUNT_FORMAT)
}

export const USAGE_COLUMN_LABELS: Readonly<Record<UsageAmountColumn, string>> = {
  usd: "Cost",
  requests: "Billed requests",
  credits: "Provider credits",
  other: "Other units",
}

/** What each unit column counts, shown as the header tooltip. */
export const USAGE_COLUMN_HINTS: Readonly<Record<UsageAmountColumn, string>> = {
  usd: "Reported provider charges in US dollars; totals include known costs only",
  requests: "Calls counted against a provider's request allowance",
  credits: "Credits the provider deducted, in its own unit",
  other: "Units recorded before unit types were tracked",
}
