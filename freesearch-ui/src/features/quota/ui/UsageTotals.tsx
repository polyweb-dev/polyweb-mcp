import { catalogNameOf } from "@/services/api/providerCatalog"
import { unitLabel } from "@/services/api/mappers"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import type { ProviderConfig } from "@/domains/providers"
import type { CRDUsageTotal, UsageTotal } from "@/domains/dashboard"
import { formatCRDAmount } from "../model/crdDisplay"
import { formatUsageP95 } from "../model/quotaDetails"

export interface UsageTotalsProps {
  usageTotals: UsageTotal[]
  crdUsageTotals: CRDUsageTotal[]
  providers: ProviderConfig[]
}

const HEAD = "grid items-center border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5 text-[12px] text-[var(--muted)]"
const CELL = "grid items-center border-b border-[var(--border-subtle)] px-4 py-3 last:border-b-0"
const FOUR = "grid-cols-[1fr_1fr_1fr_1fr]"
const FIVE = "grid-cols-[1fr_1fr_1fr_1fr_1fr]"
const CARD = "overflow-hidden rounded-lg border border-[var(--border-subtle)]"
const HEAD_BAR = "border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5"
const TITLE = "text-[13px] font-semibold text-[var(--text-strong)]"
const EMPTY = "p-8 text-center text-[13px] text-[var(--muted)]"
const NAME = "truncate text-[13px] font-medium text-[var(--text-strong)]"
const MUTED = "text-[13px] text-[var(--muted)]"

function volumeText(operation: string, volume: number): string {
  return volume + " " + (operation === "fetch" ? "URLs" : "searches")
}

/**
 * Usage totals: credit-unit cost first, then search and URL volume.
 *
 * Native totals stay in the collapsed legacy block, because native units of
 * different providers do not compare. Credit units are the one common scale.
 */
export function UsageTotals({ usageTotals, crdUsageTotals, providers }: UsageTotalsProps) {
  const p95ByProvider = new Map(providers.map((provider) => [provider.id, provider.latencyP95Ms]))
  const legacyRows = usageTotals.some((total) => total.unitKind === null)
  const nameOf = (providerId: string) => catalogNameOf(providerId) ?? providerId
  return (
    <section aria-labelledby="usage-totals-heading" className="space-y-4">
      <div className="border-b border-[var(--border-subtle)] pb-2">
        <h3 id="usage-totals-heading" className={TITLE}>Usage totals</h3>
        <p className="mt-1 text-[12px] text-[var(--muted)]">
          Credit-unit cost uses one common scale: one CRD is USD 0.001 of priced native use. Volume counts searches and fetched URLs separately.
        </p>
      </div>

      <div className={CARD}>
        <div className={HEAD_BAR}><h4 className={TITLE}>Credit-unit use</h4></div>
        {crdUsageTotals.length === 0 ? (
          <p className={EMPTY}>No credit-unit use recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <div className={HEAD + " " + FOUR}>
              <span>Provider</span><span>Operation</span><span>Attempts</span><span className="text-right">CRD cost</span>
            </div>
            {crdUsageTotals.map((total) => (
              <div key={"crd-" + total.provider + "-" + total.operation} className={CELL + " " + FOUR}>
                <div className="flex min-w-0 items-center gap-2">
                  <ProviderLogo providerId={total.provider} name={nameOf(total.provider)} />
                  <span className={NAME}>{nameOf(total.provider)}</span>
                </div>
                <span className={MUTED + " capitalize"}>{total.operation}</span>
                <span className={MUTED + " tnum"}>{total.attempt_count}</span>
                <span className="tnum text-right text-[13px] text-[var(--text)]">{formatCRDAmount(total.normalized_crd)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className={CARD}>
        <div className={HEAD_BAR}><h4 className={TITLE}>Search and URL volume</h4></div>
        {crdUsageTotals.length === 0 ? (
          <p className={EMPTY}>No volume recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <div className={HEAD + " " + FOUR}>
              <span>Provider</span><span>Operation</span><span>Volume</span><span className="text-right">p95</span>
            </div>
            {crdUsageTotals.map((total) => (
              <div key={"volume-" + total.provider + "-" + total.operation} className={CELL + " " + FOUR}>
                <span className={NAME}>{nameOf(total.provider)}</span>
                <span className={MUTED + " capitalize"}>{total.operation}</span>
                <span className={MUTED + " tnum"}>{volumeText(total.operation, total.volume_count)}</span>
                <span className={MUTED + " tnum text-right"}>{formatUsageP95(p95ByProvider.get(total.provider) ?? null)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <details className={CARD}>
        <summary className="cursor-pointer border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5 text-[13px] font-semibold text-[var(--text-strong)]">
          Legacy native totals
        </summary>
        <p className="px-4 pt-2.5 text-[12px] text-[var(--muted)]">
          Native values appear for reference only. Compare values only within the same unit.
        </p>
        {usageTotals.length === 0 ? (
          <p className={EMPTY}>No usage totals recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <div className={HEAD + " " + FIVE}>
              <span>Provider</span><span>Operation</span><span>Unit</span><span>p95</span><span className="text-right">Total units</span>
            </div>
            {usageTotals.map((total) => (
              <div key={total.provider + "-" + total.operation + "-" + (total.unitKind ?? "legacy")} className={CELL + " " + FIVE}>
                <span className={NAME}>{nameOf(total.provider)}</span>
                <span className={MUTED + " capitalize"}>{total.operation}</span>
                <span className={MUTED}>
                  {total.unitKind === null ? (
                    <span title="Recorded before canonical units existed; dimension could not be recovered">legacy (mixed)</span>
                  ) : unitLabel(total.unitKind, null)}
                </span>
                <span className={MUTED + " tnum"}>{formatUsageP95(p95ByProvider.get(total.provider) ?? null)}</span>
                <span className="tnum text-right text-[13px] text-[var(--text)]">
                  {total.total_units}
                  <span className="ml-1.5 text-[12px] text-[var(--muted)]"> ({total.eventCount} {total.eventCount === 1 ? "event" : "events"})</span>
                </span>
              </div>
            ))}
          </div>
        )}
        {legacyRows && (
          <p className="border-t border-[var(--border-subtle)] px-4 py-2.5 text-[12px] text-[var(--muted)]">
            Legacy (mixed) rows predate canonical units and are shown with their raw values only — they are excluded from dimension totals and never converted.
          </p>
        )}
      </details>
    </section>
  )
}
