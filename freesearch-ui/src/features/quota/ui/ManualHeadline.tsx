export interface ManualHeadlineProps {
  providerId: string
  providerName: string
  estimate: { percentText: string; rangeText: string; percent: number }
}

/** Manual-entry headline: estimated remaining bar from the saved window. */
export function ManualHeadline({ providerId, providerName, estimate }: ManualHeadlineProps) {
  return (
    <div className="flex flex-col-reverse gap-2" data-testid={"manual-quota-estimate-" + providerId}>
      <div
        className="w-full h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden"
        role="progressbar"
        aria-label={providerName + " estimated remaining from Manual Entry"}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={estimate.percent}
      >
        <div className="h-full rounded-full bg-[var(--signal)]" style={{ width: estimate.percent + "%" }} />
      </div>
      <span className="text-[13px] text-[var(--text)] tnum shrink-0">
        <span>{estimate.percentText}</span>
      </span>
    </div>
  )
}
