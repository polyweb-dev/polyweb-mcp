import type { UsdGrantPayload, UsdGrantsSummary } from "@/domains/dashboard"
import type { BudgetPeriod } from "@/shared/lib/budget"

export interface GrantDraft { search: string; fetch: string; period: BudgetPeriod }
export type GrantErrors = Partial<Record<"search" | "fetch", string>>

export function toDraft(grants: UsdGrantsSummary | null): GrantDraft {
  return { search: grants?.search_granted_usd ?? "", fetch: grants?.fetch_granted_usd ?? "",
    period: grants?.period ?? "month" }
}

export function validateDraft(draft: GrantDraft, fetchAvailable: boolean): GrantErrors {
  const errors: GrantErrors = {}
  const operations = fetchAvailable ? ["search", "fetch"] as const : ["search"] as const
  for (const operation of operations) {
    const amount = draft[operation].trim()
    if (amount === "") errors[operation] = "Enter an amount"
    else if (!/^\d+(\.\d{1,6})?$/.test(amount)) errors[operation] = "Use up to six decimal places"
  }
  return errors
}

export function grantPayloadOf(input: { draft: GrantDraft; authMode: string;
  grants: UsdGrantsSummary | null; fetchAvailable: boolean }): UsdGrantPayload {
  return { auth_mode: input.authMode, version: input.grants?.version ?? 0,
    period: input.draft.period, search_usd: input.draft.search.trim(),
    fetch_usd: input.fetchAvailable ? input.draft.fetch.trim() : input.grants?.fetch_granted_usd ?? "0" }
}
