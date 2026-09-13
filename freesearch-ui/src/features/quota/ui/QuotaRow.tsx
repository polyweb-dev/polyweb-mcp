import { useMemo, useState } from "react"
import type { ReactNode } from "react"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { TableCell, TableRow } from "@/shared/ui/table"
import type { ProviderConfig } from "@/domains/providers"
import type { DashboardQuota } from "@/domains/dashboard"
import { isManualQuotaEligible } from "../model/quotaEligibility"
import { formatQuotaDate, formatQuotaReset, isStaleRollingQuota, quotaCaptionFor, resolveQuota } from "../model/quotaDetails"
import { useManualQuota } from "../model/useManualQuota"
import { manualBudgetMissing, resolveQuotaRow } from "../model/quotaRowModel"
import { ManualQuotaModal, type ManualQuotaDefaults } from "./ManualQuotaModal"
import { ManualHeadline } from "./ManualHeadline"
import { QuotaHeadline } from "./QuotaHeadline"
import { QuotaRowActions } from "./QuotaRowActions"
import { QuotaRowDetail } from "./QuotaRowDetail"
import { QuotaSource } from "./QuotaSource"

export interface OAuthSlotArgs {
  providerId: string
  providerName: string
  hasUsableEstimate: boolean
  pairedSnapshot: boolean
  onPairedChange?: (paired: boolean) => void
}

export interface QuotaRowProps {
  provider: ProviderConfig
  latestQuota: DashboardQuota | undefined
  manualQuotaEligible: typeof isManualQuotaEligible
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
  isOAuthPaired?: boolean
}

export function QuotaRow({
  provider,
  latestQuota,
  manualQuotaEligible,
  renderOAuthActions,
  isOAuthPaired: isOAuthPairedProp = false,
}: QuotaRowProps) {
  const [oauthPaired, setOauthPaired] = useState(false)
  const { pairedSnapshot } = resolveQuotaRow(
    provider,
    latestQuota,
    null,
    null
  )
  const isOAuthPaired = provider.id === "parallel" && (isOAuthPairedProp || oauthPaired || pairedSnapshot)
  const { display, confidence, unitKind, displayUnit, resetAt } = resolveQuota(provider, latestQuota, isOAuthPaired)
  const quotaCaption = quotaCaptionFor(provider, latestQuota, display, isOAuthPaired)
  const [modalOpen, setModalOpen] = useState(false)

  // A saved entry promotes to the row's headline (estimated source +
  // manual bar); the vendor snapshot demotes to one quiet detail line and
  // its explainer is suppressed.
  // Exa/Parallel only offer Manual Entry while no vendor budget is
  // configured; Brave always does. When Parallel is paired via OAuth,
  // manual entry is suppressed in favor of the vendor balance.
  const budgetNotConfigured = !isOAuthPaired && manualBudgetMissing(provider, latestQuota, display.remainingPercent)
  const manualEligible = manualQuotaEligible(provider.id, budgetNotConfigured)
  const { manual, estimate: manualEstimate, save, remove } = useManualQuota(
    provider.id,
    manualEligible
  )
  const { hasUsableEstimate } = resolveQuotaRow(
    provider,
    latestQuota,
    display.remainingPercent,
    manualEstimate
  )

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
            {isStaleRollingQuota(resetAt) && display.periodLabel.toLowerCase() === "hourly" && (
              <div className="mt-1 text-[11px]" title="No successful call in the last hour; headroom recovers on next use">Stale — refreshes on next use</div>
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
          oauth={renderOAuthActions ? renderOAuthActions({
            providerId: provider.id,
            providerName: provider.name,
            hasUsableEstimate,
            pairedSnapshot,
            onPairedChange: setOauthPaired,
          }) : null}
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
            {...(manual ? { onDelete: remove } : {})}
          />
        )}
      </TableCell>
    </TableRow>
  )
}
