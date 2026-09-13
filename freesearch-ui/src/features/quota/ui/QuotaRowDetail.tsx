import { quotaDisplay } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import type { DashboardQuota } from "@/domains/dashboard"
import type { QuotaCaption } from "../model/quotaDetails"

export interface QuotaRowDetailProps {
  display: ReturnType<typeof quotaDisplay>
  quotaCaption: QuotaCaption | null
  latestQuota: DashboardQuota | undefined
  unitKind: ProviderConfig["quota"]["unitKind"]
  manualActive: boolean
}

/** Row detail cell: native values, explainer captions, and vendor detail. */
export function QuotaRowDetail({ display, quotaCaption, latestQuota, unitKind, manualActive }: QuotaRowDetailProps) {
  return (
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
}
