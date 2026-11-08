import type { CRDGrantPayload } from "@/domains/dashboard"
import { requestJson } from "@/shared/api/client"
import { multiplyDecimal } from "./manualQuotaMath"

/** The local view model retains ledger units; the public budget API uses USD. */
export function saveBudget(providerId: string, payload: CRDGrantPayload): Promise<unknown> {
  return requestJson(`/api/v1/providers/${encodeURIComponent(providerId)}/budgets/${payload.auth_mode ?? "keyed"}`, {
    method: "PUT",
    body: JSON.stringify({
      version: payload.version, period_start: payload.period_start, period_end: payload.period_end,
      search_usd: multiplyDecimal(payload.search_crd, "0.001"),
      fetch_usd: multiplyDecimal(payload.fetch_crd, "0.001"),
    }),
  })
}
