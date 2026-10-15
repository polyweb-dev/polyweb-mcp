/**
 * Manual-entry eligibility per provider.
 *
 * A provider whose vendor reports a budget or a comparable percentage needs no
 * manual anchor, because the vendor headers supply its balance. Every provider
 * of the list therefore follows the one rule. Inject a replacement to extend
 * coverage to new providers.
 *
 * Parallel stays out: its prepaid USD balance comes from the OAuth Account API
 * (poll_oauth_balance_snapshot -> AUTHORITATIVE QuotaSnapshot -> latestQuota),
 * never from a manual seed. You.com stays out the same way: its keyed USD
 * balance comes from the vendor cents balance API
 * (GET /v1/billing/account_balance -> ESTIMATED QuotaSnapshot -> latestQuota),
 * and "you" holds no catalog budget record, so the backend offers no
 * manual_anchor pool for it either. Brave, Exa, and Tinyfish keep the manual
 * seed.
 */
export const MANUAL_ENTRY_PROVIDERS = ["brave", "exa", "tinyfish"]

export function isManualQuotaEligible(providerId: string, budgetNotConfigured: boolean): boolean {
  if (!MANUAL_ENTRY_PROVIDERS.includes(providerId)) return false
  return budgetNotConfigured
}
