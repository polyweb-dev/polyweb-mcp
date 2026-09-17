/**
 * Decimal-safe math for manual billing entries.
 *
 * Allowance/usage stay verbatim decimal strings end to end (RF1: never
 * float-cast for display, never exponential notation). The remaining
 * percentage is derived with BigInt integer arithmetic only — no float math
 * — rounded half-up to 1 decimal place and clamped to 0..100.
 */

const DECIMAL_PATTERN = /^\d+(\.\d+)?$/

interface ScaledInt {
  int: bigint
  scale: number
}

function pow10(exp: number): bigint {
  let result = 1n
  for (let i = 0; i < exp; i += 1) result *= 10n
  return result
}

/** Parse a non-negative verbatim decimal ("5", "5.00", "0.88") or null. */
export function parseDecimal(value: string): ScaledInt | null {
  const trimmed = value.trim()
  if (!DECIMAL_PATTERN.test(trimmed)) return null
  const dot = trimmed.indexOf(".")
  if (dot === -1) return { int: BigInt(trimmed), scale: 0 }
  const scale = trimmed.length - dot - 1
  const digits = trimmed.slice(0, dot) + trimmed.slice(dot + 1) || "0"
  return { int: BigInt(digits), scale }
}

export function isNonNegativeDecimal(value: string): boolean {
  return parseDecimal(value) !== null
}

export function isPositiveDecimal(value: string): boolean {
  const parsed = parseDecimal(value)
  return parsed !== null && parsed.int > 0n
}

/**
 * Remaining percentage (allowance - used) / allowance * 100, rounded half-up
 * to 1 decimal place. Returns null when either side is not a decimal or the
 * allowance is not positive. Usage above allowance clamps to 0.
 *
 * Example: remainingPercent1dp("5.00", "0.88") === 82.4.
 */
export function remainingPercent1dp(allowance: string, used: string): number | null {
  const allowanceParsed = parseDecimal(allowance)
  const usedParsed = parseDecimal(used)
  if (!allowanceParsed || !usedParsed) return null
  const commonScale = Math.max(allowanceParsed.scale, usedParsed.scale)
  const allowanceInt =
    allowanceParsed.int * pow10(commonScale - allowanceParsed.scale)
  const usedInt = usedParsed.int * pow10(commonScale - usedParsed.scale)
  if (allowanceInt <= 0n) return null
  const remaining = allowanceInt - usedInt
  if (remaining <= 0n) return 0
  // Tenths of a percent, rounded half-up: q = round(remaining * 1000 / allowance).
  const numerator = remaining * 1000n
  const quotient = numerator / allowanceInt
  const remainder = numerator % allowanceInt
  const tenths = remainder * 2n >= allowanceInt ? quotient + 1n : quotient
  const clamped = tenths < 0n ? 0n : tenths > 1000n ? 1000n : tenths
  return Number(clamped) / 10
}

/** "82.4" from 82.4 — always exactly 1 decimal place. */
export function formatPercent1dp(percent: number): string {
  return percent.toFixed(1)
}

/** "Sep 1–Sep 30" for ISO YYYY-MM-DD bounds; falls back to verbatim. */
export function formatManualRange(start: string, end: string): string {
  const formatted = [start, end].map((iso) => {
    const date = new Date(iso + "T00:00:00")
    if (Number.isNaN(date.getTime())) return iso
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" })
  })
  return formatted[0] + "–" + formatted[1]
}

export interface ManualQuotaFields {
  billingStart: string
  billingEnd: string
  allowance: string
  used: string
}

export type ManualQuotaFieldErrors = Partial<Record<keyof ManualQuotaFields, string>>

const REQUIRED = "Required."

function dateError(value: string): string | null {
  if (!value) return REQUIRED
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Use a calendar date."
  return Number.isNaN(new Date(value + "T00:00:00").getTime())
    ? "Use a calendar date."
    : null
}

/** Field-level validation; empty object means the form may save. */
export function validateManualQuotaFields(fields: ManualQuotaFields): ManualQuotaFieldErrors {
  const errors: ManualQuotaFieldErrors = {}
  const startError = dateError(fields.billingStart)
  if (startError) errors.billingStart = startError
  const endError = dateError(fields.billingEnd)
  if (endError) errors.billingEnd = endError
  if (!startError && !endError && fields.billingEnd <= fields.billingStart) {
    errors.billingEnd = "Billing end must be after billing start."
  }
  if (!fields.allowance.trim()) {
    errors.allowance = REQUIRED
  } else if (!isNonNegativeDecimal(fields.allowance)) {
    errors.allowance = "Enter a non-negative amount (for example 5.00)."
  } else if (!isPositiveDecimal(fields.allowance)) {
    errors.allowance = "Allowance must be greater than zero."
  }
  if (!fields.used.trim()) {
    errors.used = REQUIRED
  } else if (!isNonNegativeDecimal(fields.used)) {
    errors.used = "Enter a non-negative amount (for example 0.88)."
  }
  return errors
}
