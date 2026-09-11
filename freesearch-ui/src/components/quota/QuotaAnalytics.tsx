import React, { useMemo, useState } from "react"
import { Clock, Database, Gauge } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { catalogNameOf } from "@/services/api/providerCatalog"
import { unitLabel } from "@/services/api/mappers"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { quotaDisplay } from "@/services/quotaDisplay"
import { ManualQuotaModal, type ManualQuotaDefaults } from "./ManualQuotaModal"
import { ParallelOAuthActions } from "../oauth/ParallelOAuthActions"
import { useManualQuota } from "./useManualQuota"
import type { BackendManualQuota } from "@/services/api/backendTypes"
import type { DashboardQuota, ProviderConfig, QuotaConfidence } from "@/types/freesearch"

/**
 * Manual-entry eligibility per provider. Brave always offers a manual
 * billing window; Exa/Parallel offer one only while no vendor budget is
 * configured. Inject a replacement to extend coverage to new providers.
 */
export function isManualQuotaEligible(providerId: string, budgetNotConfigured: boolean): boolean {
  if (providerId === "brave") return true
  if (providerId === "exa" || providerId === "parallel") return budgetNotConfigured
  return false
}

export const QuotaAnalytics: React.FC<{
  manualQuotaEligible?: typeof isManualQuotaEligible
}> = ({ manualQuotaEligible = isManualQuotaEligible }) => {
  const {
    providers,
    usageTotals,
    dashboardQuotas,
    quotaAvailable,
    dashboardNotice,
    usageLoading,
    usageError,
  } = useFreeSearch()

  const p95ByProvider = new Map(providers.map((provider) => [provider.id, provider.latencyP95Ms]))

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

      <section aria-labelledby="usage-totals-heading" className="overflow-hidden rounded-lg border border-[var(--border-subtle)]">
        <div className="border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5">
          <h3 id="usage-totals-heading" className="text-[13px] font-semibold text-[var(--text-strong)]">Usage totals</h3>
          <p className="mt-1 text-[12px] text-[var(--muted)]">
            Grouped by provider, operation, and unit. Dimensions are never
            summed together — compare values only within the same unit.
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
                key={`${total.provider}-${total.operation}-${total.unitKind ?? "legacy"}`}
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

      <section aria-labelledby="provider-quota-heading" className="overflow-hidden rounded-lg border border-[var(--border-subtle)]">
        <div className="border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5">
          <div className="flex items-center gap-2.5">
            <h3 id="provider-quota-heading" className="text-[13px] font-semibold text-[var(--text-strong)]">Provider quota view</h3>
            <span className="rounded-full border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-0.5 text-[11px] text-[var(--muted)] tnum">
              {providers.length} configured
            </span>
          </div>
          <p className="mt-1 text-[12px] text-[var(--muted)]">
            Remaining percentages use each provider&apos;s own allowance and window.
          </p>
        </div>
        <Table aria-labelledby="provider-quota-heading" className="min-w-[1080px] table-fixed text-[13px]">
          <colgroup>
            <col className="w-[16%]" />
            <col className="w-[20%]" />
            <col className="w-[14%]" />
            <col className="w-[12%]" />
            <col className="w-[25%]" />
            <col className="w-[13%]" />
          </colgroup>
          <TableHeader>
            <TableRow className="border-[var(--border-subtle)] bg-[var(--elevated)] hover:bg-[var(--elevated)]">
              {["Provider", "Remaining", "Window", "Source", "Quota details", "Actions"].map((header) => (
                <TableHead key={header} scope="col" className={`h-9 px-4 text-[12px] text-[var(--muted)] ${header === "Actions" ? "text-right" : ""}`}>
                  {header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {providers.map((provider) => (
              <QuotaRow
                key={provider.id}
                provider={provider}
                latestQuota={dashboardQuotas.find((quota) => quota.provider === provider.id)}
                manualQuotaEligible={manualQuotaEligible}
              />
            ))}
            {providers.length === 0 && (
              <TableRow><TableCell colSpan={6} className="p-8 text-center text-[var(--muted)]">No providers configured.</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </section>
    </div>
  )
}

interface QuotaRowProps {
  provider: ProviderConfig
  latestQuota: DashboardQuota | undefined
  manualQuotaEligible: typeof isManualQuotaEligible
}

interface ResolvedQuota {
  display: ReturnType<typeof quotaDisplay>
  confidence: QuotaConfidence | null
  resetAt: string | null
  unitKind: ProviderConfig["quota"]["unitKind"]
  displayUnit: string | null
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
  return {
    display,
    confidence: values.confidence,
    resetAt: values.resetAt,
    unitKind: values.unitKind,
    displayUnit: values.displayUnit,
  }
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
    return { testId: "quota-explainer-keenable", text: "Keyless usage is a locally observed Hourly; the shared per-IP pool can include traffic outside this app." }
  }
  return null
}

const QuotaRow: React.FC<QuotaRowProps> = ({ provider, latestQuota, manualQuotaEligible }) => {
  const { display, confidence, unitKind, displayUnit, resetAt } = resolveQuota(provider, latestQuota)
  const quotaCaption = quotaCaptionFor(provider, latestQuota, display)
  const [modalOpen, setModalOpen] = useState(false)

  // Exa/Parallel only offer Manual Entry while no vendor budget is
  // configured; Brave always does. A saved entry promotes to the row's
  // headline (estimated source + manual bar); the vendor snapshot demotes to
  // one quiet detail line and its explainer is suppressed.
  const noSnapshot =
    latestQuota === undefined ||
    (latestQuota.remaining === null && latestQuota.limit === null)
  const budgetNotConfigured =
    (provider.id === "exa" || provider.id === "parallel") &&
    noSnapshot &&
    display.remainingPercent === null
  const manualEligible = manualQuotaEligible(provider.id, budgetNotConfigured)
  const { manual, estimate: manualEstimate, save, remove } = useManualQuota(
    provider.id,
    manualEligible
  )
  // OAuth pairing (Parallel only, see oauth/ParallelOAuthActions): a usable
  // estimate — vendor percent, manual window, or reported balance — means
  // there is nothing to connect. An AUTHORITATIVE remaining-only snapshot
  // is itself pairing evidence, so Disconnect stays available even when
  // the status endpoint is unreachable.
  const isParallel = provider.id === "parallel"
  const vendorBalance = latestQuota !== undefined && latestQuota.remaining !== null
  const hasUsableEstimate =
    display.remainingPercent !== null || manualEstimate !== null || vendorBalance
  const pairedSnapshot =
    isParallel && latestQuota?.source === "authoritative" && latestQuota.remaining !== null
  const manualDefaults: ManualQuotaDefaults | null = useMemo(
    () =>
      manual
        ? {
            billingStart: manual.billing_start,
            billingEnd: manual.billing_end,
            allowance: manual.allowance,
            used: manual.current_usage,
          }
        : null,
    [manual]
  )

  return (
    <TableRow className="border-[var(--border-subtle)] hover:bg-[var(--elevated)] motion-reduce:transition-none">
      <TableCell className="px-4 py-4 font-medium text-[var(--text-strong)]">
        <span className="flex items-center gap-2">
          <ProviderLogo providerId={provider.id} />
          {provider.name} quota
        </span>
      </TableCell>
      <TableCell className="whitespace-normal px-4 py-4">
        {manualEstimate ? (
          <ManualHeadline providerId={provider.id} providerName={provider.name} estimate={manualEstimate} />
        ) : (
          <QuotaHeadline provider={provider} display={display} />
        )}
      </TableCell>
      <TableCell className="whitespace-normal px-4 py-4 text-[12px] text-[var(--muted)]">
        {manualEstimate && manual ? (
          <time dateTime={manual.billing_end}>{formatQuotaDate(manual.billing_end)}</time>
        ) : (
          <>
            <div>{display.periodLabel}</div>
            {display.resetLabel && (
              <div className="mt-1">Resets {formatQuotaReset(resetAt, display.periodLabel, display.resetLabel)}</div>
            )}
          </>
        )}
      </TableCell>
      <TableCell className="px-4 py-4">
        <QuotaSource confidence={manualEstimate ? "estimated" : confidence} />
      </TableCell>
      <TableCell className="whitespace-normal px-4 py-4">
        {manualEstimate && <p className="mb-1 text-[12px] text-[var(--muted)]">{manualEstimate.rangeText}</p>}
        <QuotaRowDetail
          display={display}
          quotaCaption={manualEstimate ? null : quotaCaption}
          latestQuota={latestQuota}
          unitKind={unitKind}
          manualActive={manualEstimate !== null}
        />
      </TableCell>
      <TableCell className="whitespace-normal px-4 py-4 text-right">
        <QuotaRowActions
          provider={provider}
          manualEligible={manualEligible}
          manual={manual}
          onOpenManual={() => setModalOpen(true)}
          oauth={isParallel ? (
            <ParallelOAuthActions
              providerId={provider.id}
              providerName={provider.name}
              hasUsableEstimate={hasUsableEstimate}
              pairedSnapshot={pairedSnapshot}
            />
          ) : null}
        />
        {manualEligible && modalOpen && (
          <ManualQuotaModal
            open={modalOpen}
            providerId={provider.id}
            providerName={provider.name}
            unitKind={unitKind}
            displayUnit={displayUnit}
            defaults={manualDefaults}
            onClose={() => setModalOpen(false)}
            onSave={save}
            onDelete={manual ? remove : undefined}
          />
        )}
      </TableCell>
    </TableRow>
  )
}

const QuotaSource: React.FC<{ confidence: QuotaConfidence | null }> = ({ confidence }) => (
  <span className="text-[13px] text-[var(--muted)]">
    {confidence ? (
      <ConfidenceLabel confidence={confidence} />
    ) : (
      <span title="No quota snapshot from the backend">—</span>
    )}
  </span>
)

const QuotaHeadline: React.FC<{ provider: ProviderConfig; display: ReturnType<typeof quotaDisplay> }> = ({
  provider,
  display,
}) => (
  <div className="flex flex-col-reverse gap-2">
    {display.remainingPercent !== null && (
      <div
        className="w-full h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden"
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
    </span>
  </div>
)

const ManualHeadline: React.FC<{
  providerId: string
  providerName: string
  estimate: { percentText: string; rangeText: string; percent: number }
}> = ({ providerId, providerName, estimate }) => (
  <div className="flex flex-col-reverse gap-2" data-testid={`manual-quota-estimate-${providerId}`}>
    <div
      className="w-full h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden"
      role="progressbar"
      aria-label={`${providerName} estimated remaining from Manual Entry`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={estimate.percent}
    >
      <div className="h-full rounded-full bg-[var(--signal)]" style={{ width: `${estimate.percent}%` }} />
    </div>
    <span className="text-[13px] text-[var(--text)] tnum shrink-0">
      <span>{estimate.percentText}</span>
    </span>
  </div>
)

const ManualBudgetButton: React.FC<{
  providerId: string
  providerName: string
  label: string
  onOpen: () => void
}> = ({ providerId, providerName, label, onOpen }) => (
  <Button
    type="button"
    variant="outline"
    size="lg"
    className="px-3"
    data-testid={`manual-quota-open-${providerId}`}
    aria-label={`${label} for ${providerName}`}
    onClick={onOpen}
  >
    {label}
  </Button>
)

const QuotaRowActions: React.FC<{
  provider: ProviderConfig
  manualEligible: boolean
  manual: BackendManualQuota | null
  onOpenManual: () => void
  oauth: React.ReactNode
}> = ({ provider, manualEligible, manual, onOpenManual, oauth }) => {
  if (!manualEligible && oauth === null) return null
  return (
    <span className="flex flex-wrap items-center justify-end gap-2">
      {manualEligible ? (
        <ManualBudgetButton
          providerId={provider.id}
          providerName={provider.name}
          label={manual ? "Update usage" : "Set budget"}
          onOpen={onOpenManual}
        />
      ) : null}
      {oauth}
    </span>
  )
}

const QuotaRowDetail: React.FC<{
  display: ReturnType<typeof quotaDisplay>
  quotaCaption: { testId: string; text: string } | null
  latestQuota: DashboardQuota | undefined
  unitKind: ProviderConfig["quota"]["unitKind"]
  manualActive: boolean
}> = ({ display, quotaCaption, latestQuota, unitKind, manualActive }) => (
  <>
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-[var(--muted)]">
      {manualActive ? (
        <span className="tnum" title="Vendor snapshot; the manual estimate above leads this row">
          Vendor: {display.nativeValue} · {display.confidenceLabel}
        </span>
      ) : (
        <span className="tnum" title="Native provider units; retained for detail">{display.nativeValue}</span>
      )}
    </div>
    {!manualActive && (quotaCaption ? (
      <span data-testid={quotaCaption.testId} className="mt-1 block text-[12px] leading-relaxed text-[var(--muted)]">{quotaCaption.text}</span>
    ) : latestQuota && display.detail ? (
      <span className="mt-1 block text-[12px] leading-relaxed text-[var(--muted)]">
        {display.detail}{unitKind === "USD" ? " Call equivalents are derived, not a vendor limit." : ""}
      </span>
    ) : null)}
  </>
)

const ConfidenceLabel: React.FC<{ confidence: QuotaConfidence }> = ({ confidence }) => (
  <span
    className="text-[12px] capitalize text-[var(--muted)]"
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

function formatUsageP95(latency: number | null): string {
  return latency === null ? "\u2014" : `${latency}ms`
}

function formatQuotaDate(value: string): string {
  const date = new Date(`${value}T00:00:00`)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

function formatQuotaReset(resetAt: string | null, period: string, fallback: string): string {
  if (!resetAt || period.toLowerCase() !== "hourly") return fallback
  const date = new Date(resetAt)
  if (Number.isNaN(date.getTime())) return fallback
  return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true })
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
