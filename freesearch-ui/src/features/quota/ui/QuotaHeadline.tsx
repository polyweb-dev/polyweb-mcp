import { quotaDisplay } from "@/services/quotaDisplay"
import type { ProviderConfig } from "@/types/freesearch"

export interface QuotaHeadlineProps {
  provider: ProviderConfig
  display: ReturnType<typeof quotaDisplay>
}

/** Vendor headline: remaining bar plus the comparable percentage line. */
export function QuotaHeadline({ provider, display }: QuotaHeadlineProps) {
  return (
    <div className="flex flex-col-reverse gap-2">
      {display.remainingPercent !== null && (
        <div
          className="w-full h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden"
          role="progressbar"
          aria-label={provider.name + " quota remaining"}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={display.remainingPercent}
        >
          <div className="h-full rounded-full bg-[var(--signal)]" style={{ width: display.remainingPercent + "%" }} />
        </div>
      )}
      <span className="text-[13px] text-[var(--text)] tnum shrink-0">
        <span data-testid={"quota-remaining-percent-" + provider.id}>{display.headline}</span>
      </span>
    </div>
  )
}
