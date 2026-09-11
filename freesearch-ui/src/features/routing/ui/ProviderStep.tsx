import { ProviderLogo } from "@/components/common/ProviderLogo"
import { providerQuotaDisplay } from "@/services/quotaDisplay"
import type { ProviderConfig } from "@/types/freesearch"

export interface ProviderStepProps {
  index: string
  provider: ProviderConfig
  reason: string
  highlight?: boolean
}

/** One evaluated provider in the pipeline with quota and p95 context. */
export function ProviderStep({ index, provider, reason, highlight }: ProviderStepProps) {
  const quota = providerQuotaDisplay(provider)
  const headline = quota.remainingPercent === null ? "Quota unavailable" : quota.remainingPercent + "% remaining"
  return (
    <div
      className={"flex items-start gap-3 p-3 rounded-md border transition-all " + (highlight
        ? "bg-[var(--surface)] border-[var(--signal)]/40"
        : "bg-[var(--surface)] border-[var(--border-subtle)]")}
    >
      <span className="mt-0.5 w-6 h-6 rounded-full bg-[var(--signal-muted)] border border-[var(--signal)]/40 flex items-center justify-center shrink-0 text-[12px] font-medium text-[var(--signal)] tnum">
        {index}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <ProviderLogo providerId={provider.id} />
            <span className="text-[13px] font-semibold text-[var(--text-strong)] truncate">
              {provider.name}
            </span>
          </div>
          {highlight && (
            <span className="text-[12px] px-1.5 py-0.5 rounded bg-[var(--signal-muted)] text-[var(--signal)] font-medium">
              Primary
            </span>
          )}
          <span className="text-[13px] text-[var(--text)] tnum">
            {provider.latencyP95Ms === null ? "—" : provider.latencyP95Ms + " ms"} p95
          </span>
        </div>
        <div className="flex items-center justify-between gap-2 mt-0.5 text-[13px] text-[var(--muted)]">
          <span>{reason}</span>
          <span
            className="tnum shrink-0"
            title={
              provider.quota.observedAt
                ? "Remaining quota (" + provider.quota.confidence + ", " + (provider.quota.displayUnit ?? provider.quota.unit) + ")"
                : "Quota unavailable from the backend"
            }
          >
            Quota {headline}
            <span className="ml-1.5 text-[11px] text-[var(--muted)]">({quota.nativeValue})</span>
          </span>
        </div>
      </div>
    </div>
  )
}
