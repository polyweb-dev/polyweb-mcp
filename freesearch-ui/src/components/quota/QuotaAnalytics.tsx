import React from "react"
import { Clock, Database, Gauge } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { catalogNameOf } from "@/services/api/providerCatalog"
import { unitLabel } from "@/services/api/mappers"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { quotaDisplay } from "@/services/quotaDisplay"
import type { DashboardQuota, ProviderConfig, QuotaConfidence } from "@/types/freesearch"

export const QuotaAnalytics: React.FC = () => {
  const {
    providers,
    usageTotals,
    dashboardQuotas,
    quotaAvailable,
    dashboardNotice,
    usageLoading,
    usageError,
  } = useFreeSearch()

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-2 pb-2 border-b border-[var(--border-subtle)]">
        <h2 className="text-[var(--text-strong)]">Usage</h2>
        <p className="text-[13px] text-[var(--muted)]">
          Recorded provider usage and quota signals reported by the backend.
        </p>
        {dashboardNotice && <p className="text-[12px] text-[var(--muted)]">{dashboardNotice}</p>}
      </div>

      {usageError && (
        <p
          role="alert"
          className="p-3 rounded border border-[var(--status-danger)]/40 bg-[var(--elevated)] text-[13px]"
          style={{ color: "var(--status-danger)" }}
        >
          Usage data unavailable — {usageError}
        </p>
      )}

      {usageLoading && (
        <p className="text-[13px] text-[var(--muted)]" role="status">Loading usage telemetry...</p>
      )}
      {!usageLoading && (
        // GAP: 7 — the dashboard can have no authoritative quota records.
        // GAP: 8 — cache telemetry is not part of the backend dashboard contract.
        <p className="p-3 rounded border border-[var(--border-subtle)] bg-[var(--elevated)] text-[13px] text-[var(--muted)]">
          {quotaAvailable
            ? "Quota data available; cache telemetry unavailable."
            : "Quota unavailable from the backend; cache telemetry unavailable."}
        </p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <KpiCard icon={<Gauge className="size-4 text-[var(--signal)] shrink-0" />} label="Recorded aggregates">
          <span className="tnum">{usageTotals.length}</span> provider operations
        </KpiCard>
        <KpiCard icon={<Clock className="size-4 text-[var(--status-warning)] shrink-0" />} label="Quota signal">
          {quotaAvailable ? "Available" : "No quota source"}
        </KpiCard>
        <KpiCard icon={<Database className="size-4 text-[var(--muted)] shrink-0" />} label="Cache telemetry">
          No cache signal
        </KpiCard>
      </div>

      <section className="space-y-3">
        <div>
          <h3 className="text-[var(--text-strong)]">Usage totals</h3>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Grouped by provider, operation, and unit. Dimensions are never
            summed together — compare values only within the same unit.
          </p>
        </div>
        {usageTotals.length === 0 ? (
          <p className="p-8 text-center border border-[var(--border-subtle)] rounded-lg bg-[var(--elevated)] text-[13px] text-[var(--muted)]">
            No usage totals recorded yet.
          </p>
        ) : (
          <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
            <div className="grid grid-cols-[1fr_1fr_1fr_1fr] items-center py-2.5 px-4 bg-[var(--elevated)] border-b border-[var(--border-subtle)] text-[12px] text-[var(--muted)]">
              <span>Provider</span>
              <span>Operation</span>
              <span>Unit</span>
              <span className="text-right">Total units</span>
            </div>
            {usageTotals.map((total) => (
              <div
                key={`${total.provider}-${total.operation}-${total.unitKind ?? "legacy"}`}
                className="grid grid-cols-[1fr_1fr_1fr_1fr] items-center py-3 px-4 border-b last:border-b-0 border-[var(--border-subtle)]"
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
          <p className="text-[12px] text-[var(--muted)]">
            Legacy (mixed) rows predate canonical units and are shown with
            their raw values only — they are excluded from dimension totals
            and never converted.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <div>
          <h3 className="text-[var(--text-strong)]">Provider quota view</h3>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Remaining percentages are normalized against each provider&apos;s own
            allowance and window. Native units and source details stay below.
          </p>
        </div>
        <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
          {providers.map((provider) => (
             <QuotaRow
               key={provider.id}
               provider={provider}
               latestQuota={dashboardQuotas.find((quota) => quota.provider === provider.id)}
             />
           ))}
        </div>
      </section>
    </div>
  )
}

interface QuotaRowProps {
  provider: ProviderConfig
  latestQuota: DashboardQuota | undefined
}

interface ResolvedQuota {
  display: ReturnType<typeof quotaDisplay>
  confidence: QuotaConfidence | null
  resetAt: string | null
  unitKind: ProviderConfig["quota"]["unitKind"]
}

interface QuotaValues {
  remaining: string | null
  remainingPercent: string | null
  limit: string | null
  unitKind: ProviderConfig["quota"]["unitKind"]
  displayUnit: string | null
  confidence: QuotaConfidence | null
  resetAt: string | null
  window: string | null
}

function quotaValues(provider: ProviderConfig, latest: DashboardQuota | undefined): QuotaValues {
  const base = provider.quota
  if (!latest) {
    return {
      remaining: base.remaining,
      remainingPercent: base.remainingPercent,
      limit: base.limit,
      unitKind: base.unitKind,
      displayUnit: base.displayUnit,
      confidence: base.observedAt ? base.confidence : null,
      resetAt: base.nextReset !== "—" ? base.nextReset : null,
      window: base.window,
    }
  }
  return {
    remaining: latest.remaining,
    remainingPercent: latest.remainingPercent,
    limit: latest.limit,
    unitKind: latest.unitKind,
    displayUnit: latest.displayUnit,
    confidence: latest.source,
    resetAt: latest.resetAt,
    window: latest.window,
  }
}

function resolveQuota(provider: ProviderConfig, latestQuota: DashboardQuota | undefined): ResolvedQuota {
  const values = quotaValues(provider, latestQuota)
  const display = quotaDisplay({
    ...values,
    providerId: provider.id,
    keyless: provider.id === "keenable" && provider.keyVaultStatus === "keyless_public",
  })
  return { display, confidence: values.confidence, resetAt: values.resetAt, unitKind: values.unitKind }
}

function quotaCaptionFor(
  provider: ProviderConfig,
  latestQuota: DashboardQuota | undefined,
  display: ReturnType<typeof quotaDisplay>
): { testId: string; text: string } | null {
  const noSnapshot = latestQuota === undefined || (latestQuota.remaining === null && latestQuota.limit === null)
  if (!noSnapshot || display.remainingPercent !== null) return null
  if (provider.id === "parallel") {
    return { testId: "quota-explainer-parallel", text: "No API-key balance endpoint is available. Configure a local monthly USD budget to calculate remaining capacity." }
  }
  if (provider.id === "exa") {
    return { testId: "quota-explainer-exa", text: "Per-response USD spend is tracked. A remaining percentage needs a monthly budget or Exa Admin usage credentials." }
  }
  if (provider.id === "brave") {
    return { testId: "quota-explainer-brave", text: "Brave reports monthly request quota in response headers. An absent or unbounded limit has no remaining percentage." }
  }
  if (provider.id === "keenable") {
    return { testId: "quota-explainer-keenable", text: "Keyless usage is a locally observed rolling hour; the shared per-IP pool can include traffic outside this app." }
  }
  return null
}

const QuotaRow: React.FC<QuotaRowProps> = ({ provider, latestQuota }) => {
  const { display, confidence, resetAt, unitKind } = resolveQuota(provider, latestQuota)
  const quotaCaption = quotaCaptionFor(provider, latestQuota, display)
  return (
    <div className="grid grid-cols-[1fr_1fr_1.5fr] items-center gap-4 py-3 px-4 border-b last:border-b-0 border-[var(--border-subtle)]">
      <span className="flex items-center gap-2 min-w-0 text-[13px] font-medium text-[var(--text-strong)]">
        <ProviderLogo providerId={provider.id} />
        {provider.name} quota
      </span>
      <QuotaSource confidence={confidence} resetAt={resetAt} />
      <QuotaHeadline provider={provider} display={display} />
      <QuotaRowDetail
        display={display}
        quotaCaption={quotaCaption}
        latestQuota={latestQuota}
        unitKind={unitKind}
      />
    </div>
  )
}

const QuotaSource: React.FC<{ confidence: QuotaConfidence | null; resetAt: string | null }> = ({
  confidence,
  resetAt,
}) => (
  <span className="text-[13px] text-[var(--muted)]">
    {confidence ? <ConfidenceBadge confidence={confidence} /> : <span title="No quota snapshot from the backend">—</span>}
    {resetAt && <span className="ml-1.5" title={`Quota resets at ${resetAt}`}>· resets {formatReset(resetAt)}</span>}
  </span>
)

const QuotaHeadline: React.FC<{ provider: ProviderConfig; display: ReturnType<typeof quotaDisplay> }> = ({
  provider,
  display,
}) => (
  <div className="flex items-center gap-3">
    {display.remainingPercent !== null && (
      <div
        className="flex-1 h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden"
        role="progressbar"
        aria-label={`${provider.name} quota remaining`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={display.remainingPercent}
      >
        <div className="h-full rounded-full bg-[var(--signal)]" style={{ width: `${display.remainingPercent}%` }} />
      </div>
    )}
    <span className="text-[13px] text-[var(--text)] tnum shrink-0">
      <span data-testid={`quota-remaining-percent-${provider.id}`}>{display.headline}</span>
      <span className="ml-1.5 text-[11px] uppercase tracking-wide text-[var(--muted)]">
        {display.periodLabel}
      </span>
    </span>
  </div>
)

const QuotaRowDetail: React.FC<{
  display: ReturnType<typeof quotaDisplay>
  quotaCaption: { testId: string; text: string } | null
  latestQuota: DashboardQuota | undefined
  unitKind: ProviderConfig["quota"]["unitKind"]
}> = ({ display, quotaCaption, latestQuota, unitKind }) => (
  <>
    <div className="col-span-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-[var(--muted)]">
      <span className="tnum" title="Native provider units; retained for detail">{display.nativeValue}</span>
      <span aria-label={`Quota source ${display.confidenceLabel}`}>· {display.confidenceLabel}</span>
      {display.resetLabel && <span>· resets {display.resetLabel}</span>}
    </div>
    {quotaCaption ? (
      <span data-testid={quotaCaption.testId} className="col-span-3 text-[12px] text-[var(--muted)]">{quotaCaption.text}</span>
    ) : latestQuota && display.detail ? (
      <span className="col-span-3 text-[12px] text-[var(--muted)]">
        {display.detail}{unitKind === "USD" ? " Call equivalents are derived, not a vendor limit." : ""}
      </span>
    ) : null}
  </>
)

const ConfidenceBadge: React.FC<{ confidence: QuotaConfidence }> = ({ confidence }) => (
  <span
    className="inline-block text-[11px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide border border-[var(--border-subtle)] bg-[var(--surface)] text-[var(--muted)]"
    title={
      confidence === "authoritative"
        ? "Polled directly from the vendor"
        : confidence === "observed"
          ? "Observed from vendor response headers or local counters"
          : "Estimated locally; not a vendor balance"
    }
  >
    {confidence}
  </span>
)

function formatReset(resetAt: string): string {
  const date = new Date(resetAt)
  if (Number.isNaN(date.getTime())) return resetAt
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

const KpiCard: React.FC<{ icon: React.ReactNode; label: string; children: React.ReactNode }> = ({
  icon,
  label,
  children,
}) => (
  <div className="p-3.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] flex items-center gap-3">
    {icon}
    <div>
      <div className="text-[12px] text-[var(--muted)]">{label}</div>
      <div className="text-[14px] font-medium text-[var(--text-strong)]">{children}</div>
    </div>
  </div>
)
