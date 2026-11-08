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

function formatScaled(value: bigint, scale: number): string {
  if (scale === 0) return value.toString()
  const divisor = pow10(scale)
  const fraction = (value % divisor).toString().padStart(scale, "0")
  return value / divisor + "." + fraction
}

/**
 * Exact product of two verbatim decimals: "5" x "0.001" gives "0.005".
 *
 * Example: multiplyDecimal("4500", "0.001") === "4.500".
 */
export function multiplyDecimal(left: string, right: string): string | null {
  const first = parseDecimal(left)
  const second = parseDecimal(right)
  if (!first || !second) return null
  return formatScaled(first.int * second.int, first.scale + second.scale)
}

/**
 * Exact difference of two verbatim decimals, or null when a side is not a
 * decimal or the result is negative.
 *
 * Example: subtractDecimal("5.00", "4.12") === "0.88".
 */
export function subtractDecimal(left: string, right: string): string | null {
  const first = parseDecimal(left)
  const second = parseDecimal(right)
  if (!first || !second) return null
  const scale = Math.max(first.scale, second.scale)
  const result = first.int * pow10(scale - first.scale) - second.int * pow10(scale - second.scale)
  return result < 0n ? null : formatScaled(result, scale)
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

/** `usage` asks for current usage; `balance` asks for the remaining balance. */
export type ManualAmountMode = "usage" | "balance"

export type ManualQuotaFieldErrors = Partial<Record<keyof ManualQuotaFields, string>>

const REQUIRED = "Enter a value"

export function calendarDateError(value: string): string | null {
  if (!value) return REQUIRED
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Enter a valid date"
  const parsed = new Date(value + "T00:00:00Z")
  return Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value
    ? "Enter a valid date"
    : null
}

function periodErrors(fields: ManualQuotaFields): ManualQuotaFieldErrors {
  const errors: ManualQuotaFieldErrors = {}
  const startError = calendarDateError(fields.billingStart)
  if (startError) errors.billingStart = startError
  const endError = calendarDateError(fields.billingEnd)
  if (endError) errors.billingEnd = endError
  if (!startError && !endError && fields.billingEnd <= fields.billingStart) {
    errors.billingEnd = "Billing end must be after billing start"
  }
  return errors
}

function allowanceError(value: string): string | undefined {
  if (!value.trim()) return REQUIRED
  if (!isNonNegativeDecimal(value)) return "Enter a non-negative amount (for example 5.00)."
  if (!isPositiveDecimal(value)) return "Allowance must be greater than zero."
  return undefined
}

/**
 * The second amount is current usage, or the remaining balance in balance mode.
 * A balance above the allowance cannot encode a negative usage, so it fails.
 */
function amountError(
  fields: ManualQuotaFields,
  amountMode: ManualAmountMode
): string | undefined {
  if (!fields.used.trim()) return REQUIRED
  if (!isNonNegativeDecimal(fields.used)) {
    return "Enter a non-negative amount (for example 0.88)."
  }
  const balanceTooHigh =
    amountMode === "balance" &&
    isPositiveDecimal(fields.allowance) &&
    subtractDecimal(fields.allowance, fields.used) === null
  return balanceTooHigh ? "The remaining balance cannot exceed the allowance." : undefined
}

/** Field-level validation; empty object means the form may save. */
export function validateManualQuotaFields(
  fields: ManualQuotaFields,
  amountMode: ManualAmountMode = "usage"
): ManualQuotaFieldErrors {
  const errors = periodErrors(fields)
  const allowance = allowanceError(fields.allowance)
  if (allowance) errors.allowance = allowance
  const amount = amountError(fields, amountMode)
  if (amount) errors.used = amount
  return errors
}
