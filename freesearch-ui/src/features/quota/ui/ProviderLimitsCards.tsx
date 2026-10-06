import type { ReactNode } from "react"
import type { CRDUsageTotal, ProviderLimits } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import { Footnote } from "./Footnote"
import { ProviderLimitsCard } from "./ProviderLimitsCard"

export interface ProviderLimitsCardsProps {
  providers: ProviderConfig[]
  providerLimits: ProviderLimits[]
  /** Every reported credit-unit use row of the dashboard. */
  crdUsageTotals: CRDUsageTotal[]
  refreshDashboard: () => Promise<void>
  /** Providers that may hold a manual native anchor. */
  manualEligible: ReadonlySet<string>
}

/** Credit-unit use rows of one provider; a card receives its own rows only. */
function usageFor(totals: CRDUsageTotal[], providerId: string): CRDUsageTotal[] {
  return totals.filter((total) => total.provider === providerId)
}

/**
 * Credit-unit card list for the configured providers.
 *
 * A provider appears only when the payload reports a limit entry for it, so a
 * rail the backend does not support never gains an invented card. The card list
 * keeps both auth modes in the payload; each card shows its active rail.
 */
export function ProviderLimitsCards({
  providers,
  providerLimits,
  crdUsageTotals,
  refreshDashboard,
  manualEligible,
}: ProviderLimitsCardsProps): ReactNode {
  const entries = providers
    .map((provider) => ({
      provider,
      limits: providerLimits.find((entry) => entry.provider === provider.id),
    }))
    .filter(
      (entry): entry is { provider: ProviderConfig; limits: ProviderLimits } =>
        entry.limits !== undefined,
    )

  return (
    <section aria-labelledby="crd-cards-heading" className="space-y-3">
      <div className="flex items-center gap-2.5">
        <h3 id="crd-cards-heading" className="text-[13px] font-semibold text-[var(--text-strong)]">
          Provider credit units
        </h3>
        <span className="rounded-full border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-0.5 text-[11px] text-[var(--muted)] tnum">
          {entries.length} reported
        </span>
      </div>
      {entries.length === 0 ? (
        <p className="rounded-lg border border-[var(--border-subtle)] p-8 text-center text-[13px] text-[var(--muted)]">
          No provider limit data reported by the backend.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
          {entries.map((entry) => (
            <ProviderLimitsCard
              key={entry.provider.id}
              providerId={entry.provider.id}
              providerName={entry.provider.name}
              limits={entry.limits}
              crdUsageTotals={usageFor(crdUsageTotals, entry.provider.id)}
              refreshDashboard={refreshDashboard}
              manualEligible={manualEligible.has(entry.provider.id)}
            />
          ))}
        </div>
      )}
      <Footnote className="border-t border-[var(--border-subtle)]/60 pt-2">
        Vendor funds in one common scale: one CRD is USD 0.001 of priced native use. Amounts show
        at most one decimal digit; the exact value governs admission, debit, and audit.
      </Footnote>
    </section>
  )
}
