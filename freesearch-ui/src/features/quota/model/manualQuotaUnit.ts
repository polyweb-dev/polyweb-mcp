import type { ProviderAuthLimits } from "@/domains/dashboard"
import { normalizeUnitKind, type UnitKind } from "@/shared/api/units"
import type { ManualAmountMode } from "./manualQuotaMath"

export interface ManualUnit {
  unitKind: UnitKind | null
  displayUnit: string | null
  amountMode: ManualAmountMode
}

function usdBudgetOf(auth: ProviderAuthLimits): boolean {
  return [auth.search, auth.fetch].some((record) => {
    const budget = record?.budget
    return budget?.model === "usd" && budget.allowance_unit.trim().toUpperCase() === "USD"
  })
}

function nativeUnitOf(auth: ProviderAuthLimits, providerId: string): string | null {
  const declaredUnit = auth.aggregate_pool?.native_unit ?? auth.detail?.native_unit ?? null
  if (declaredUnit !== null) return declaredUnit
  if (usdBudgetOf(auth)) return "USD"
  return providerId === "exa" ? "USD" : null
}

function displayUnitOf(unitKind: UnitKind): string {
  if (unitKind === "CREDIT") return "credits"
  return unitKind === "FREE" ? "Free" : unitKind
}

export function manualUnit(auth: ProviderAuthLimits, providerId: string): ManualUnit {
  const nativeUnit = nativeUnitOf(auth, providerId)
  const unitKind = normalizeUnitKind(nativeUnit)
  if (unitKind === "USD") return { unitKind, displayUnit: "USD", amountMode: "balance" }
  if (unitKind === null) return { unitKind: null, displayUnit: null, amountMode: "usage" }
  return { unitKind, displayUnit: displayUnitOf(unitKind), amountMode: "usage" }
}
