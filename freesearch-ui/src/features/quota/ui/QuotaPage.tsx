import type { ReactNode } from "react"
import { Clock, Database, Gauge } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { isManualQuotaEligible } from "../model/quotaEligibility"
import { KpiCard } from "./KpiCard"
import { ProviderLimitsCards } from "./ProviderLimitsCards"
import { QuotaTable } from "./QuotaTable"
import type { OAuthSlotArgs } from "./QuotaRow"
import { UsageTotals } from "./UsageTotals"

export interface QuotaPageProps {
  manualQuotaEligible?: typeof isManualQuotaEligible
  /**
   * OAuth pairing controls per provider row. Supplied by composition (the
   * quota overlay stays in app composition) so the quota feature never
   * imports the OAuth feature directly.
   */
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
}

/** Usage page: credit-unit cards, recorded aggregates, and the legacy grid. */
export function QuotaPage({
  manualQuotaEligible = isManualQuotaEligible,
  renderOAuthActions,
}: QuotaPageProps) {

  const {
    providers,
    usageTotals,
    providerLimits,
    crdUsageTotals,
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
          Credit-unit capacity and recorded provider usage reported by the backend.
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

      <ProviderLimitsCards providers={providers} providerLimits={providerLimits} />

      <UsageTotals
        usageTotals={usageTotals}
        crdUsageTotals={crdUsageTotals}
        providers={providers}
      />

      <details className="overflow-hidden rounded-lg border border-[var(--border-subtle)]">
        <summary className="cursor-pointer border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5 text-[13px] font-semibold text-[var(--text-strong)]">
          Legacy native quota view
        </summary>
        <p className="px-4 py-2.5 text-[12px] text-[var(--muted)]">
          Vendor native balances, manual native budgets, and manual usage entries. Credit units are
          the primary view above; this grid stays available for native reconciliation.
        </p>
        <QuotaTable
          providers={providers}
          dashboardQuotas={dashboardQuotas}
          manualQuotaEligible={manualQuotaEligible}
          {...(renderOAuthActions !== undefined ? { renderOAuthActions } : {})}
        />
      </details>

    </div>
  )
}
