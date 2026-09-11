import { ProviderLogo } from "@/components/common/ProviderLogo"
import { TableCell, TableRow } from "@/components/ui/table"
import { providerQuotaDisplay } from "@/services/quotaDisplay"
import type { ProviderConfig } from "@/types/freesearch"

export interface RankRowProps {
  provider: ProviderConfig
  rank: number
  role: string
}

/** One evaluated rank row: position, provider, latency, quota, role. */
export function RankRow({ provider, rank, role }: RankRowProps) {
  const quota = providerQuotaDisplay(provider)
  const headline = quota.remainingPercent === null ? "Quota unavailable" : quota.remainingPercent + "% remaining"
  return (
    <TableRow className="border-b border-[var(--border-subtle)] last:border-b-0">
      <TableCell className="px-3 py-2.5 text-[var(--muted)] tnum">#{rank}</TableCell>
      <TableCell className="px-3 py-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <ProviderLogo providerId={provider.id} />
          <span className="font-medium text-[var(--text-strong)] truncate">{provider.name}</span>
          {provider.capabilities.includes("keyless_tier") && (
            <span className="text-[12px] px-1 rounded bg-[var(--elevated)] text-[var(--muted)]">
              free
            </span>
          )}
        </div>
      </TableCell>
      <TableCell className="px-3 py-2.5 text-right text-[var(--text)] tnum">
        {provider.latencyP95Ms === null ? "—" : provider.latencyP95Ms + "ms"}
      </TableCell>
      <TableCell className="px-3 py-2.5 text-right text-[var(--muted)] tnum">
        <span
          title={
            provider.quota.observedAt
              ? "Remaining quota (" + provider.quota.confidence + ", " + (provider.quota.displayUnit ?? provider.quota.unit) + ")"
              : "Quota unavailable from the backend"
          }
        >
          <span data-testid={"rank-quota-percent-" + provider.id}>{headline}</span>
          <span className="ml-1.5 text-[11px] text-[var(--muted)]">({quota.nativeValue})</span>
        </span>
      </TableCell>
      <TableCell className="px-3 py-2.5 text-right">
        <span
          className={
            role === "Primary"
              ? "text-[13px] font-medium text-[var(--signal)]"
              : role === "Fallback"
                ? "text-[13px] text-[var(--text)]"
                : "text-[13px] text-[var(--muted)]"
          }
        >
          {role}
        </span>
      </TableCell>
    </TableRow>
  )
}
