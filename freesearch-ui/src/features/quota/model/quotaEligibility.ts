/**
 * Manual-entry eligibility per provider.
 *
 * A provider whose vendor reports a budget or a comparable percentage needs no
 * manual anchor, because the vendor headers supply its balance. Every provider
 * of the list therefore follows the one rule. Inject a replacement to extend
 * coverage to new providers.
 */
export const MANUAL_ENTRY_PROVIDERS = ["brave", "exa", "parallel", "tinyfish"]

export function isManualQuotaEligible(providerId: string, budgetNotConfigured: boolean): boolean {
  if (!MANUAL_ENTRY_PROVIDERS.includes(providerId)) return false
  return budgetNotConfigured
}
