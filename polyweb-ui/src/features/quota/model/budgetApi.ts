import type { UsdGrantPayload } from "@/domains/dashboard"
import { requestJson } from "@/shared/api/client"

/** Save exact decimal USD amounts for a recurring calendar period. */
export function saveBudget(providerId: string, payload: UsdGrantPayload): Promise<unknown> {
  const { auth_mode = "keyed", ...body } = payload
  return requestJson(`/api/v1/providers/${encodeURIComponent(providerId)}/budgets/${auth_mode}`, {
    method: "PUT", body: JSON.stringify(body),
  })
}
