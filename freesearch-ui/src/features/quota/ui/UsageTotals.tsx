import { catalogNameOf } from "@/services/api/providerCatalog"
import { unitLabel } from "@/services/api/mappers"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import type { ProviderConfig, UsageTotal } from "@/types/freesearch"
import { formatUsageP95 } from "../model/quotaDetails"

export interface UsageTotalsProps {
  usageTotals: UsageTotal[]
  providers: ProviderConfig[]
}

/** Recorded aggregates grouped by provider, operation, and unit. */
export function UsageTotals({ usageTotals, providers }: UsageTotalsProps) {
  const p95ByProvider = new Map(providers.map((provider) => [provider.id, provider.latencyP95Ms]))
  return (
    <section aria-labelledby="usage-totals-heading" className="overflow-hidden rounded-lg border border-[var(--border-subtle)]">
      <div className="border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5">
        <h3 id="usage-totals-heading" className="text-[13px] font-semibold text-[var(--text-strong)]">Usage totals</h3>
        <p className="mt-1 text-[12px] text-[var(--muted)]">
          Grouped by provider, operation, and unit. Compare values only within the same unit.
        </p>
      </div>
      {usageTotals.length === 0 ? (
        <p className="p-8 text-center text-[13px] text-[var(--muted)]">
          No usage totals recorded yet.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <div className="grid grid-cols-[1fr_1fr_1fr_1fr_1fr] items-center py-2.5 px-4 bg-[var(--elevated)] border-b border-[var(--border-subtle)] text-[12px] text-[var(--muted)]">
            <span>Provider</span>
            <span>Operation</span>
            <span>Unit</span>
            <span>p95</span>
            <span className="text-right">Total units</span>
          </div>
          {usageTotals.map((total) => (
            <div
              key={total.provider + "-" + total.operation + "-" + (total.unitKind ?? "legacy")}
              className="grid grid-cols-[1fr_1fr_1fr_1fr_1fr] items-center py-3 px-4 border-b last:border-b-0 border-[var(--border-subtle)]"
            >
              <div className="flex items-center gap-2 min-w-0">
                <ProviderLogo providerId={total.provider} name={catalogNameOf(total.provider)} />
                <span className="text-[13px] font-medium text-[var(--text-strong)] truncate">
                  {catalogNameOf(total.provider) ?? total.provider}
                </span>
              </div>
              <span className="text-[13px] capitalize text-[var(--muted)]">{total.operation}</span>
              <span className="text-[13px] text-[var(--muted)]">
                {total.unitKind === null ? (
                  <span title="Recorded before canonical units existed; dimension could not be recovered">
                    legacy (mixed)
                  </span>
                ) : (
                  unitLabel(total.unitKind, null)
                )}
              </span>
              <span className="text-[13px] tnum text-[var(--muted)]">
                {formatUsageP95(p95ByProvider.get(total.provider) ?? null)}
              </span>
              <span className="text-right text-[13px] tnum text-[var(--text)]">
                {total.total_units}
                <span className="ml-1.5 text-[12px] text-[var(--muted)]">
                  ({total.eventCount} {total.eventCount === 1 ? "event" : "events"})
                </span>
              </span>
            </div>
          ))}
        </div>
      )}
      {usageTotals.some((total) => total.unitKind === null) && (
        <p className="border-t border-[var(--border-subtle)] px-4 py-2.5 text-[12px] text-[var(--muted)]">
          Legacy (mixed) rows predate canonical units and are shown with
          their raw values only — they are excluded from dimension totals
          and never converted.
        </p>
      )}
    </section>
  )
}
