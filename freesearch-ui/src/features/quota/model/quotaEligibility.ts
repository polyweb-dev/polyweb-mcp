/**
 * Manual-entry eligibility per provider. Brave always offers a manual
 * billing window; Exa/Parallel offer one only while no vendor budget is
 * configured. Inject a replacement to extend coverage to new providers.
 */
export function isManualQuotaEligible(providerId: string, budgetNotConfigured: boolean): boolean {
  if (providerId === "brave") return true
  if (["exa", "parallel", "tinyfish", "firecrawl", "tavily"].includes(providerId)) return budgetNotConfigured
  return false
}
