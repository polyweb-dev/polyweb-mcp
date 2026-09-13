import { useFreeSearch } from "@/context/useFreeSearch"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { getProviderReason } from "@/domains/routing"
import { providerQuotaDisplay } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"

export interface FallbackCascadeProps {
  fallbacks: ProviderConfig[]
  preset: ReturnType<typeof useFreeSearch>["routingPreset"]
}

/** Failover cascade: ordered fallback providers below the primary. */
export function FallbackCascade({ fallbacks, preset }: FallbackCascadeProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-[13px] text-[var(--muted)]">
        <span className="font-medium text-[var(--text)]">Failover cascade</span>
        <span className="tnum">{fallbacks.length} fallbacks ready</span>
      </div>

      {fallbacks.map((fallback, idx) => {
        const quota = providerQuotaDisplay(fallback)
        const headline = quota.remainingPercent === null ? "Quota unavailable" : quota.remainingPercent + "% remaining"
        return (
          <div
            key={fallback.id}
            className="flex items-center justify-between p-2.5 rounded bg-[var(--surface)] border border-[var(--border-subtle)]"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <span className="text-[12px] text-[var(--muted)] tnum">#{idx + 2}</span>
              <ProviderLogo providerId={fallback.id} />
              <span className="text-[13px] font-medium text-[var(--text)] truncate">
                {fallback.name}
              </span>
              <span className="text-[12px] text-[var(--muted)]">
                {fallback.capabilities.includes("keyless_tier") ? "Keyless free tier" : "P" + fallback.priority}
              </span>
            </div>
            <div className="flex items-center gap-3 text-[12px] text-[var(--muted)] tnum shrink-0">
              <span>{fallback.latencyP95Ms === null ? "—" : fallback.latencyP95Ms + "ms"}</span>
              <span
                title={
                  fallback.quota.observedAt
                    ? "Remaining quota (" + fallback.quota.confidence + ", " + (fallback.quota.displayUnit ?? fallback.quota.unit) + ")"
                    : "Quota unavailable from the backend"
                }
              >
                {headline}
                <span className="ml-1.5 text-[11px] text-[var(--muted)]">({quota.nativeValue})</span>
              </span>
              <span className="hidden sm:inline">{getProviderReason(fallback, idx + 1, preset)}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
