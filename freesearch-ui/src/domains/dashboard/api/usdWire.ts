/** Translate USD transport fields to the existing internal ledger view model. */
function credits(value: unknown): unknown {
  if (typeof value !== "string" && typeof value !== "number") return value
  const match = /^(\d+)(?:\.(\d+))?$/.exec(String(value))
  if (!match) return null
  const fraction = match[2] ?? ""
  const digits = BigInt(match[1] + fraction) * 1000n
  const scale = fraction.length
  const padded = digits.toString().padStart(scale + 1, "0")
  return scale === 0 ? padded : (padded.slice(0, -scale) + "." + padded.slice(-scale)).replace(/\.?0+$/, "")
}

const NAMES: Record<string, string> = {
  usd_views: "crd_views", spend_usd: "normalized_crd", debit_usd: "crd_debit",
  balance_split_note: "crd_split_note", spend_totals: "crd_usage_totals",
}
const MONEY = /^(remaining|local_remaining|request_cost|allowance|search_granted|search_consumed|search_reserved|fetch_granted|fetch_consumed|fetch_reserved|old|new)_usd$/

export function ledgerView(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(ledgerView)
  if (value === null || typeof value !== "object") return value
  return Object.fromEntries(Object.entries(value).map(([key, item]) => {
    if (key === "spend_usd" || key === "debit_usd" || MONEY.test(key)) {
      return [NAMES[key] ?? key.replace(/_usd$/, "_crd"), credits(item)]
    }
    return [NAMES[key] ?? key, ledgerView(item)]
  }))
}
