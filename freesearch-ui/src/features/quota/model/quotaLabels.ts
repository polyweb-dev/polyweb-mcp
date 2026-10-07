/**
 * Human labels of the provider limit facts.
 *
 * One name covers one item here: the two credit controls, every audit source
 * key, every audit reason key, and every native pool id. No raw backend key
 * therefore reaches the UI text, and no control gains a second name.
 */

/** The credit control that records the balance of the vendor dashboard. */
export const BALANCE_ENTRY = "Provider Balance"
/** One sentence that states what the provider balance control records. */
export const BALANCE_ENTRY_NOTE = "Records the balance the vendor dashboard shows, as an estimate."
/** The credit control that sets the local spend ceiling. */
export const SPEND_CAP = "Budget Limit"
/** One sentence that states what the budget limit control does. */
export const SPEND_CAP_NOTE = "Sets a local credit-unit ceiling that adds no vendor funds."
/** One visible sentence that states the difference between the two controls. */
export const CONTROL_SPLIT_NOTE =
  BALANCE_ENTRY +
  " records the vendor dashboard balance as an estimate. " +
  SPEND_CAP +
  " sets a local credit-unit ceiling."

/** The credit tier of one rail: the free facts, the paid facts, or both. */
export type CreditMode = "free" | "paid" | "both"
/** The short tier word of one credit mode, for the credit note. */
export const CREDIT_MODE_WORD: Record<CreditMode, string> = {
  free: "Free",
  paid: "Paid",
  both: "Free + Paid",
}
/** The option label of one credit mode, for the mode combo. */
export const CREDIT_MODE_LABEL: Record<CreditMode, string> = {
  free: "Free credits",
  paid: "Paid credits",
  both: "Free + Paid",
}
/** The mode options in the shown order. */
export const CREDIT_MODES: CreditMode[] = ["free", "paid", "both"]
/** The label of the mode combo. */
export const CREDIT_MODE_FIELD = "Credit mode"

/** Source keys that mean "no source reported"; they yield no text. */
const ABSENT_KEYS = ["", "unknown", "n/a", "none"]

/** One text per priced or recorded operation. */
const OPERATION_TEXT: Record<string, string> = {
  fetch: "Fetch",
  search: "Search",
}

/** One sentence per audit source key. */
const SOURCE_TEXT: Record<string, string> = {
  documented: "Documented price",
  local: "Local use",
  local_daily_estimate: "Daily estimate (UTC)",
  local_ledger: "Local ledger",
  manual_anchor: BALANCE_ENTRY,
  operator: "Operator action",
  operator_grant: SPEND_CAP,
  vendor_api: "Vendor API",
  vendor_headers: "Vendor headers",
}

/** One name per audit reason key. */
const REASON_TEXT: Record<string, string> = {
  grant: SPEND_CAP,
  manual_anchor: BALANCE_ENTRY,
}

/** One text per native unit of a pool id. */
const UNIT_TEXT: Record<string, string> = {
  credit: "credits",
  free: "free",
  request: "requests",
  token: "tokens",
  usd: "USD",
}

/** Sentence case of one raw key: separators become spaces and the first letter a capital. */
export function humanKey(key: string): string {
  const text = key.replace(/[:_]+/g, " ").trim()
  if (text === "") return ""
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Human text of one audit source key; an absent source yields no text. */
export function sourceLabel(source: string | null | undefined): string {
  if (source === null || source === undefined) return ""
  const key = source.trim().toLowerCase()
  if (ABSENT_KEYS.includes(key)) return ""
  return SOURCE_TEXT[key] ?? humanKey(key)
}

/** Human text of one audit reason key; an absent reason yields no text. */
export function reasonLabel(reason: string | null | undefined): string {
  if (reason === null || reason === undefined) return ""
  const key = reason.trim().toLowerCase()
  if (ABSENT_KEYS.includes(key)) return ""
  return REASON_TEXT[key] ?? humanKey(key)
}

/** Human name of one native pool id: `brave:keyed:usd` becomes `Keyed USD`. */
export function poolName(poolId: string | null | undefined): string {
  if (poolId === null || poolId === undefined) return ""
  const text = poolId.trim()
  if (text === "") return ""
  const parts = text.split(":")
  if (parts.length !== 3) return humanKey(text)
  const mode = humanKey(parts[1])
  const unit = UNIT_TEXT[parts[2].toLowerCase()] ?? humanKey(parts[2])
  return [mode, unit].filter((part) => part !== "").join(" ")
}

/** Text of one priced or recorded operation. */
export function operationLabel(operation: string | null | undefined): string {
  if (operation === null || operation === undefined) return ""
  const key = operation.trim().toLowerCase()
  if (key === "") return ""
  return OPERATION_TEXT[key] ?? humanKey(key)
}
