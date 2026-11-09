import type { UsdConversionProfile } from "@/domains/dashboard"
import { formatDate } from "@/shared/lib/formatTime"
import { multiplyDecimal } from "./manualQuotaMath"

export function grantHint(input: {
  name: string
  value: string
  conversion: UsdConversionProfile | null
  reference: string
}): string | null {
  if (input.name === "start" || input.name === "end") {
    return input.value ? formatDate(input.value + "T00:00:00") : "Date, e.g. " + formatDate("2026-11-01T00:00:00")
  }
  if (input.value.trim() === "") return null
  const price = input.conversion === null ? input.reference : input.conversion.native_usd_per_unit
  if (price === null) return null
  const raw = multiplyDecimal(input.value, price)
  if (raw === null) return null
  const usd = Number(raw).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return "≈ $" + usd + " at provider list price"
}
