import React from "react"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import {
  TableCell,
  TableRow,
} from "@/components/ui/table"
import type { ProviderConfig } from "@/types/freesearch"

export const RankRow: React.FC<{ provider: ProviderConfig; rank: number; role: string }> = ({
  provider,
  rank,
  role,
}) => (
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
      {provider.quota.used ?? "—"}/{provider.quota.limit ?? "∞"}
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
