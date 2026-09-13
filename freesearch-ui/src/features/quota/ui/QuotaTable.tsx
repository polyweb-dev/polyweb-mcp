import type { ReactNode } from "react"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/shared/ui/table"
import type { ProviderConfig } from "@/domains/providers"
import type { DashboardQuota } from "@/domains/dashboard"
import { isManualQuotaEligible } from "../model/quotaEligibility"
import { QuotaRow, type OAuthSlotArgs } from "./QuotaRow"

export interface QuotaTableProps {
  providers: ProviderConfig[]
  dashboardQuotas: DashboardQuota[]
  manualQuotaEligible: typeof isManualQuotaEligible
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
}

/** Provider quota grid: one row per configured provider. */
export function QuotaTable({
  providers,
  dashboardQuotas,
  manualQuotaEligible,
  renderOAuthActions,
}: QuotaTableProps) {
  return (
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
              <TableHead key={header} scope="col" className={"h-9 px-4 text-[12px] text-[var(--muted)]" + (header === "Actions" ? " text-right" : "")}>
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
              {...(renderOAuthActions !== undefined ? { renderOAuthActions } : {})}
            />
          ))}

          {providers.length === 0 && (
            <TableRow><TableCell colSpan={6} className="p-8 text-center text-[var(--muted)]">No providers configured.</TableCell></TableRow>
          )}
        </TableBody>
      </Table>
    </section>
  )
}
