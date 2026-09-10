import React, { useMemo, useState } from "react"
import { Search } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { SegmentedControl } from "@/components/common/SegmentedControl"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { FallbackConfig, ProviderConfig } from "@/types/freesearch"
import { providerQuotaDisplay } from "@/services/quotaDisplay"
import { getEligibleProviders } from "./routingUtils"

type RanksOperation = "Search" | "Fetch"

const RANKS_OPERATIONS: readonly RanksOperation[] = ["Search", "Fetch"]

function getProviderRole(index: number, fallbackConfig: FallbackConfig): string {
  if (index === 0) return "Primary"
  if (fallbackConfig.enabled && index <= fallbackConfig.maxAttempts) return "Fallback"
  return "Standby"
}

/**
 * Evaluated provider rank: recomputed eligibility for the selected operation
 * with a case-insensitive provider text filter.
 */
export const ProviderRanks: React.FC = () => {
  const { providers, fallbackConfig, routingPreset } = useFreeSearch()
  const [operation, setOperation] = useState<RanksOperation>("Search")
  const [filterText, setFilterText] = useState("")

  const op = operation.toLowerCase() as "search" | "fetch"
  const eligible = useMemo(
    () => getEligibleProviders(providers, op, routingPreset),
    [providers, op, routingPreset]
  )

  const normalizedFilter = filterText.trim().toLowerCase()
  // Rank and role are derived from the UNFILTERED eligible order first; the
  // text filter then only decides which rows stay visible.
  const ranked = useMemo(
    () =>
      eligible.map((provider, index) => ({
        provider,
        rank: index + 1,
        role: getProviderRole(index, fallbackConfig),
      })),
    [eligible, fallbackConfig]
  )
  const visible = normalizedFilter
    ? ranked.filter((entry) => entry.provider.name.toLowerCase().includes(normalizedFilter))
    : ranked

  return (
    <section className="space-y-4 w-full max-w-none">
      <p className="text-[12px] text-[var(--muted)]">
        Remaining percentages are comparable; details keep each provider&apos;s native unit.
      </p>
      <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden w-full">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5">
          <div className="flex items-center gap-2.5">
            <h3 className="text-[13px] font-semibold text-[var(--text-strong)]">Evaluated rank</h3>
            <span className="rounded-full border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-0.5 text-[11px] text-[var(--muted)] tnum">
              {eligible.length} active
            </span>
            <span className="hidden sm:inline text-[12px] text-[var(--muted)]">
              Primary: <strong className="text-[var(--text-strong)] font-medium">{ranked[0]?.provider.name ?? "None"}</strong>
            </span>
          </div>

          <div className="flex items-center gap-3">
            <SegmentedControl
              options={RANKS_OPERATIONS}
              value={operation}
              onChange={(next) => setOperation(next as RanksOperation)}
              ariaLabel="Ranks operation"
            />
            <div className="relative flex items-center">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute left-2.5 size-3.5 text-[var(--muted)]"
              />
              <input
                type="text"
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                placeholder="Filter providers..."
                aria-label="Filter providers by name"
                className="w-48 rounded-md border border-[var(--border-subtle)] bg-[var(--surface)] pl-8 pr-3 py-1.5 text-[12px] text-[var(--text)] placeholder:text-[var(--muted)] outline-none focus:border-[var(--signal)]"
              />
            </div>
          </div>
        </div>

        <Table className="text-[13px]">
          <TableHeader>
            <TableRow className="bg-[var(--elevated)] hover:bg-[var(--elevated)] border-b border-[var(--border-subtle)]">
              <TableHead className="h-9 px-3 text-[12px] text-[var(--muted)]">Rank</TableHead>
              <TableHead className="h-9 px-3 text-[12px] text-[var(--muted)]">Provider</TableHead>
              <TableHead className="h-9 px-3 text-[12px] text-[var(--muted)] text-right">
                Latency
              </TableHead>
              <TableHead className="h-9 px-3 text-[12px] text-[var(--muted)] text-right">
                Quota
              </TableHead>
              <TableHead className="h-9 px-3 text-[12px] text-[var(--muted)] text-right">
                Role
              </TableHead>
            </TableRow>
          </TableHeader>

          <TableBody>
            {visible.map((entry) => (
              <RankRow
                key={entry.provider.id}
                provider={entry.provider}
                rank={entry.rank}
                role={entry.role}
              />
            ))}
            {visible.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="px-3 py-6 text-center text-[13px] text-[var(--muted)]">
                  No providers match this filter.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  )
}

const RankRow: React.FC<{ provider: ProviderConfig; rank: number; role: string }> = ({
  provider,
  rank,
  role,
}) => {
  const quota = providerQuotaDisplay(provider)
  const headline = quota.remainingPercent === null ? "Quota unavailable" : `${quota.remainingPercent}% remaining`
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
      {provider.latencyP95Ms === null ? "—" : `${provider.latencyP95Ms}ms`}
    </TableCell>
    <TableCell className="px-3 py-2.5 text-right text-[var(--muted)] tnum">
      <span
        title={
          provider.quota.observedAt
            ? `Remaining quota (${provider.quota.confidence}, ${provider.quota.displayUnit ?? provider.quota.unit})`
            : "Quota unavailable from the backend"
        }
      >
        <span data-testid={`rank-quota-percent-${provider.id}`}>{headline}</span>
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
