import type { LimitRateWindow, ProviderAuthLimits } from "@/domains/dashboard"
import { callsText } from "./usdDisplay"

interface ProviderRateFact {
  label: string
  value: string
  note: string | null
}

const RATE_WINDOW_ORDER = ["1s", "1m", "1h", "1d"]
const WINDOW_WORD: Record<string, string> = { "1s": "second", "1m": "minute", "1h": "hour", "1d": "day" }
const RATE_UNIT_WORD: Record<string, string> = { requests: "requests", urls: "URLs" }
/** Plain words for the rate scope, so no raw enum reaches the popover. */
const SCOPE_WORD: Record<string, string> = {
  key: "per key",
  ip: "per IP address",
  team: "per team",
  org: "per organization",
}

function knownLimit(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  return text === "" || text.toLowerCase() === "unknown" || text === "n/a" ? null : text
}

function rateWindowOf(windows: LimitRateWindow[]): LimitRateWindow | null {
  for (const window of RATE_WINDOW_ORDER) {
    const entry = windows.find((item) => item.window === window && knownLimit(item.limit) !== null)
    if (entry !== undefined) return entry
  }
  return null
}

function rateFact(
  windows: LimitRateWindow[],
  wholeRequests: boolean,
  label: string,
): ProviderRateFact | null {
  const entry = rateWindowOf(windows)
  const limit = entry === null ? null : knownLimit(entry.limit)
  if (entry === null || limit === null) return null
  const count = wholeRequests && entry.unit === "requests" ? callsText(limit) : limit
  if (count === null) return null
  const unit = RATE_UNIT_WORD[entry.unit] ?? entry.unit
  const window = WINDOW_WORD[entry.window] ?? entry.window
  const scopeKey = knownLimit(entry.scope)
  const scope = scopeKey === null ? null : (SCOPE_WORD[scopeKey.toLowerCase()] ?? null)
  return {
    label,
    value: count + " " + unit + " per " + window,
    note: scope === null ? null : "(" + scope + ")",
  }
}

/** Rate facts for one provider, keeping Exa's and You.com's operation ceilings distinct. */
export function providerRateFacts(
  auth: ProviderAuthLimits,
  providerId: string | undefined,
  wholeRequests: boolean,
): ProviderRateFact[] {
  if (providerId === "exa" || providerId === "youcom") {
    return [
      rateFact(auth.search?.rate?.windows ?? [], wholeRequests, "Search rate limit"),
      rateFact(auth.fetch?.rate?.windows ?? [], wholeRequests, "Fetch rate limit"),
    ].filter((fact): fact is ProviderRateFact => fact !== null)
  }
  const rate = rateFact(auth.detail?.rate_windows ?? [], wholeRequests, "Rate limit")
  return rate === null ? [] : [rate]
}
