import React from "react"
import { DollarSign, Database, TrendingDown, Clock } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"

export const QuotaAnalytics: React.FC = () => {
  const { providers, cacheStats } = useFreeSearch()

  const totalFreeReqsUsed = providers
    .filter((p) => p.capabilities.includes("keyless_tier"))
    .reduce((acc, p) => acc + p.quota.used, 0)

  const cacheHits = cacheStats.searchHits + cacheStats.fetchHits
  const estimatedSavingsUsd = (totalFreeReqsUsed * 0.015 + cacheHits * 0.02).toFixed(2)

  return (
    <div className="space-y-8">
      {/* Page heading */}
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-2 pb-2 border-b border-[var(--border-subtle)]">
        <div>
          <h2 className="text-[var(--text-strong)]">Usage</h2>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Provider quota limits, tier consumption tracking, and zero-cost savings telemetry.
          </p>
        </div>

        <span className="text-[13px] tnum" style={{ color: "var(--status-healthy)" }}>
          ~${estimatedSavingsUsd} saved this cycle
        </span>
      </div>

      {/* KPI Cards across widescreen */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <KpiCard icon={<DollarSign className="size-4 shrink-0" style={{ color: "var(--status-healthy)" }} />} label="Calculated savings">
          <span className="tnum" style={{ color: "var(--status-healthy)" }}>
            ${estimatedSavingsUsd}
          </span>
        </KpiCard>

        <KpiCard icon={<TrendingDown className="size-4 text-[var(--signal)] shrink-0" />} label="Zero-cost requests">
          <span className="tnum">{totalFreeReqsUsed} queries</span>
        </KpiCard>

        <KpiCard icon={<Database className="size-4 shrink-0" style={{ color: "var(--signal)" }} />} label="Cache roundtrips saved">
          <span className="tnum">{cacheHits} hits</span>
        </KpiCard>

        <KpiCard icon={<Clock className="size-4 text-[var(--status-warning)] shrink-0" />} label="Monitored windows">
          <span className="tnum">{providers.length} provider quotas</span>
        </KpiCard>
      </div>

      {/* Consumption Table */}
      <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
        {/* Table header */}
        <div
          className="grid items-center text-[13px] font-medium py-2.5 px-4 bg-[var(--elevated)] border-b border-[var(--border-subtle)] text-[var(--muted)]"
          style={{
            gridTemplateColumns: "220px 140px 1fr 140px 140px",
          }}
        >
          <span>Provider</span>
          <span>Window</span>
          <span>Consumption</span>
          <span className="text-right">Confidence</span>
          <span className="text-right">Resets</span>
        </div>

        {/* Provider quota rows */}
        {providers.map((p) => {
          const quota = p.quota
          const percentUsed = quota.limit
            ? Math.min(100, Math.round((quota.used / quota.limit) * 100))
            : 0

          const barColor =
            percentUsed > 80
              ? "var(--status-danger)"
              : percentUsed > 50
              ? "var(--status-warning)"
              : "var(--signal)"

          return (
            <div
              key={p.id}
              className="grid items-center py-3.5 px-4 border-b last:border-b-0 border-[var(--border-subtle)] hover:bg-[var(--elevated)] transition-colors"
              style={{
                gridTemplateColumns: "220px 140px 1fr 140px 140px",
              }}
            >
              {/* Provider name */}
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-medium text-[var(--text-strong)]">
                  {p.name}
                </span>
                {p.capabilities.includes("keyless_tier") && (
                  <span
                    className="text-[12px] px-1 rounded"
                    style={{
                      background: "rgba(34, 197, 94, 0.1)",
                      color: "var(--status-healthy)",
                    }}
                  >
                    free
                  </span>
                )}
              </div>

              {/* Reset period */}
              <span className="text-[13px] text-[var(--muted)]">
                {quota.resetPeriod}
              </span>

              {/* Progress bar + numbers */}
              <div className="flex items-center gap-3 pr-6">
                <div
                  className="flex-1 h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden"
                >
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${percentUsed}%`,
                      background: barColor,
                    }}
                  />
                </div>
                <span className="text-[13px] text-[var(--text)] tnum shrink-0">
                  {quota.used}/{quota.limit || "∞"} {quota.unit}
                </span>
              </div>

              {/* Confidence */}
              <span className="text-right text-[13px] text-[var(--muted)]">
                {quota.confidence}
              </span>

              {/* Next reset */}
              <span className="text-right text-[13px] text-[var(--text)] tnum">
                {quota.nextReset}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const KpiCard: React.FC<{
  icon: React.ReactNode
  label: string
  children: React.ReactNode
}> = ({ icon, label, children }) => (
  <div className="p-3.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] flex items-center gap-3">
    {icon}
    <div>
      <div className="text-[12px] text-[var(--muted)]">{label}</div>
      <div className="text-[14px] font-medium text-[var(--text-strong)]">{children}</div>
    </div>
  </div>
)
