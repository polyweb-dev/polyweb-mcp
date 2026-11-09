/**
 * Display helpers for amounts on the Quotas page: thousands separators on
 * the leading integer and plain native-unit amounts.
 */
import { formatLatency } from "@/shared/lib/formatTime"

/** Thousands separators on the first integer of one shown amount. */
export function groupDigits(text: string): string {
  return text.replace(/\d+/, (digits) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ","))
}

/** Human labels for stored unit codes. */
export function nativeUnitLabel(unit: string): string {
  const key = unit.trim().toUpperCase()
  if (["CREDIT", "CREDITS"].includes(key)) return "credits"
  if (key === "FREE") return "Free"
  if (key === "USD") return "USD"
  return key === "REQUEST" ? "requests" : unit.toLowerCase()
}

/** One exact decimal shown with separators and at most two fraction digits. */
function shortNumber(amount: string, fractionDigits: number): string | null {
  const value = Number(amount.trim())
  if (!Number.isFinite(value)) return null
  return value.toLocaleString("en-US", { maximumFractionDigits: fractionDigits })
}

/**
 * The remaining amount of one vendor pool in its own unit: "$192.33 left",
 * "1,320 credits left", "400 requests left". An unknown unit yields null.
 */
export function nativeLeftText(amount: string, unit: string): string | null {
  const key = unit.trim().toUpperCase()
  if (key === "FREE") return "Free"
  if (key === "USD") {
    const value = Number(amount.trim())
    if (!Number.isFinite(value)) return null
    return "$" + value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " left"
  }
  if (!["CREDIT", "CREDITS", "REQUEST"].includes(key)) return null
  const noun = nativeUnitLabel(unit)
  const text = shortNumber(amount, 1)
  return text === null ? null : text + " " + noun + " left"
}

/** Latency with separators and a space before the unit: "1,192 ms"; unknown stays empty. */
export function latencyText(milliseconds: number | null): string {
  return milliseconds === null ? "" : formatLatency(milliseconds)
}
