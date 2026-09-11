import { useMemo, useState } from "react"
import type { ReactNode } from "react"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { TableCell, TableRow } from "@/components/ui/table"
import type { DashboardQuota, ProviderConfig } from "@/types/freesearch"
import { isManualQuotaEligible } from "../model/quotaEligibility"
import { formatQuotaDate, formatQuotaReset, quotaCaptionFor, resolveQuota } from "../model/quotaDetails"
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
}

export interface QuotaRowProps {
  provider: ProviderConfig
  latestQuota: DashboardQuota | undefined
  manualQuotaEligible: typeof isManualQuotaEligible
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
}

export function QuotaRow({ provider, latestQuota, manualQuotaEligible, renderOAuthActions }: QuotaRowProps) {
  const { display, confidence, unitKind, displayUnit, resetAt } = resolveQuota(provider, latestQuota)
  const quotaCaption = quotaCaptionFor(provider, latestQuota, display)
  const [modalOpen, setModalOpen] = useState(false)

  // A saved entry promotes to the row's headline (estimated source +
  // manual bar); the vendor snapshot demotes to one quiet detail line and
  // its explainer is suppressed.
  // Exa/Parallel only offer Manual Entry while no vendor budget is
  // configured; Brave always does. A saved entry promotes to the row's
  // headline (estimated source + manual bar); the vendor snapshot demotes to
  // one quiet detail line and its explainer is suppressed.
  const budgetNotConfigured = manualBudgetMissing(provider, latestQuota, display.remainingPercent)
  const manualEligible = manualQuotaEligible(provider.id, budgetNotConfigured)
  const { manual, estimate: manualEstimate, save, remove } = useManualQuota(
    provider.id,
    manualEligible
  )
  const { hasUsableEstimate, pairedSnapshot } = resolveQuotaRow(
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
            onDelete={manual ? remove : undefined}
          />
        )}
      </TableCell>
    </TableRow>
  )
}
