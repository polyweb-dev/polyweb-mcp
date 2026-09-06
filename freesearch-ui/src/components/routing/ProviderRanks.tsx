import React, { useMemo, useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
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
    <section className="space-y-4 max-w-4xl">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h3 className="text-[var(--text-strong)]">Evaluated rank</h3>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Recomputed ordering the resolver would follow for this operation.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <SegmentedControl
            options={RANKS_OPERATIONS}
            value={operation}
            onChange={(next) => setOperation(next as RanksOperation)}
            ariaLabel="Ranks operation"
          />
          <input
            type="text"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder="Filter providers..."
            aria-label="Filter providers by name"
            className="w-44 rounded-md border border-[var(--border-subtle)] bg-[var(--surface)] px-3 py-1.5 text-[13px] text-[var(--text)] placeholder:text-[var(--muted)] outline-none focus:border-[var(--signal)]"
          />
        </div>
      </div>

      <h4 className="text-[14px] text-[var(--text-strong)]">
        Evaluated provider rank ({eligible.length} active)
      </h4>

      <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
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
}) => (
  <TableRow className="border-b border-[var(--border-subtle)] last:border-b-0">
    <TableCell className="px-3 py-2.5 text-[var(--muted)] tnum">#{rank}</TableCell>
    <TableCell className="px-3 py-2.5">
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-medium text-[var(--text-strong)] truncate">{provider.name}</span>
        {provider.capabilities.includes("keyless_tier") && (
          <span className="text-[12px] px-1 rounded bg-[var(--elevated)] text-[var(--muted)]">
            free
          </span>
        )}
      </div>
    </TableCell>
    <TableCell className="px-3 py-2.5 text-right text-[var(--text)] tnum">
      {provider.latencyP95Ms}ms
    </TableCell>
    <TableCell className="px-3 py-2.5 text-right text-[var(--muted)] tnum">
      {provider.quota.used}/{provider.quota.limit ?? "∞"}
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
