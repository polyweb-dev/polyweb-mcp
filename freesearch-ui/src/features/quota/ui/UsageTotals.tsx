import { catalogNameOf } from "@/services/api/providerCatalog"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import type { ProviderConfig } from "@/domains/providers"
import type { CRDUsageTotal } from "@/domains/dashboard"
import { formatCRDAmount } from "../model/crdDisplay"
import { formatUsageP95 } from "../model/quotaDetails"
import { Footnote } from "./Footnote"

export interface UsageTotalsProps {
  crdUsageTotals: CRDUsageTotal[]
  providers: ProviderConfig[]
}

const HEAD = "grid items-center border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5 text-[12px] text-[var(--muted)]"
const CELL = "grid items-center border-b border-[var(--border-subtle)] px-4 py-3 last:border-b-0"
const FOUR = "grid-cols-[1fr_1fr_1fr_1fr]"
const CARD = "overflow-hidden rounded-lg border border-[var(--border-subtle)]"
const HEAD_BAR = "border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5"
const TITLE = "text-[13px] font-semibold text-[var(--text-strong)]"
const EMPTY = "p-8 text-center text-[13px] text-[var(--muted)]"
const NAME = "truncate text-[13px] font-medium text-[var(--text-strong)]"
const MUTED = "text-[13px] text-[var(--muted)]"

function volumeText(operation: string, volume: number): string {
  return volume + " " + (operation === "fetch" ? "URLs" : "searches")
}

/** A known p95 only; an unreported latency yields no text at all. */
function p95Text(providers: ProviderConfig[], providerId: string): string {
  const latency = providers.find((provider) => provider.id === providerId)?.latencyP95Ms ?? null
  return formatUsageP95(latency)
}

/**
 * Usage totals: credit-unit cost first, then search and URL volume.
 *
 * Native totals left this page with the legacy grid, because native units of
 * different providers do not compare. Credit units are the one common scale.
 */
export function UsageTotals({ crdUsageTotals, providers }: UsageTotalsProps) {
  const nameOf = (providerId: string) => catalogNameOf(providerId) ?? providerId
  return (
    <section aria-labelledby="usage-totals-heading" className="space-y-4">
      <h3 id="usage-totals-heading" className={TITLE}>Usage totals</h3>

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
            {crdUsageTotals.map((total) => {
              const p95 = p95Text(providers, total.provider)
              return (
                <div key={"volume-" + total.provider + "-" + total.operation} className={CELL + " " + FOUR}>
                  <span className={NAME}>{nameOf(total.provider)}</span>
                  <span className={MUTED + " capitalize"}>{total.operation}</span>
                  <span className={MUTED + " tnum"}>{volumeText(total.operation, total.volume_count)}</span>
                  {p95 === "" ? (
                    <span />
                  ) : (
                    <span className={MUTED + " tnum text-right"}>{p95}</span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <Footnote className="border-t border-[var(--border-subtle)]/60 pt-2">
        Credit-unit cost uses one common scale: one CRD is USD 0.001 of priced native use. Volume counts searches and fetched URLs separately.
      </Footnote>
    </section>
  )
}
