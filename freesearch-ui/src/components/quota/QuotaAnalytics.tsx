import React from "react"
import { Clock, Database, Gauge } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { catalogNameOf } from "@/services/api/providerCatalog"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import type { DashboardQuota, ProviderConfig } from "@/types/freesearch"

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
            Units and event counts are shown exactly as recorded.
          </p>
        </div>
        {usageTotals.length === 0 ? (
          <p className="p-8 text-center border border-[var(--border-subtle)] rounded-lg bg-[var(--elevated)] text-[13px] text-[var(--muted)]">
            No usage totals recorded yet.
          </p>
        ) : (
          <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
            <div className="grid grid-cols-[1fr_1fr_1fr] items-center py-2.5 px-4 bg-[var(--elevated)] border-b border-[var(--border-subtle)] text-[12px] text-[var(--muted)]">
              <span>Provider</span>
              <span>Operation</span>
              <span className="text-right">Total units</span>
            </div>
            {usageTotals.map((total) => (
              <div
                key={`${total.provider}-${total.operation}`}
                className="grid grid-cols-[1fr_1fr_1fr] items-center py-3 px-4 border-b last:border-b-0 border-[var(--border-subtle)]"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <ProviderLogo providerId={total.provider} name={catalogNameOf(total.provider)} />
                  <span className="text-[13px] font-medium text-[var(--text-strong)] truncate">
                    {catalogNameOf(total.provider) ?? total.provider}
                  </span>
                </div>
                <span className="text-[13px] capitalize text-[var(--muted)]">{total.operation}</span>
                <span className="text-right text-[13px] tnum text-[var(--text)]">{total.total_units}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div>
          <h3 className="text-[var(--text-strong)]">Provider quota view</h3>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Limits remain blank when the backend has no quota source.
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

const QuotaRow: React.FC<QuotaRowProps> = ({ provider, latestQuota }) => {
  const { quota } = provider
  const remaining = latestQuota?.remaining ?? null
  const limit = latestQuota?.limit ?? null
  const hasValues = remaining !== null && limit !== null
  const percent = hasValues
    ? Math.min(100, Math.round((Number(remaining) / Number(limit)) * 100))
    : 0
  return (
    <div className="grid grid-cols-[1fr_1fr_1.5fr] items-center gap-4 py-3 px-4 border-b last:border-b-0 border-[var(--border-subtle)]">
      <span className="flex items-center gap-2 min-w-0 text-[13px] font-medium text-[var(--text-strong)]">
        <ProviderLogo providerId={provider.id} />
        {provider.name} quota
      </span>
      <span className="text-[13px] text-[var(--muted)]">{quota.resetPeriod ?? "—"}</span>
      <div className="flex items-center gap-3">
        {hasValues && (
          <div className="flex-1 h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
            <div className="h-full rounded-full bg-[var(--signal)]" style={{ width: `${percent}%` }} />
          </div>
        )}
        <span className="text-[13px] text-[var(--text)] tnum shrink-0">
          {remaining ?? "—"}/{limit ?? "∞"} {quota.unit}
        </span>
      </div>
    </div>
  )
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
