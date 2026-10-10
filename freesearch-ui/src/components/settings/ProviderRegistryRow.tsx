import React from "react"
import { RefreshCw } from "lucide-react"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { Button } from "@/shared/ui/button"
import {
  TableCell,
  TableRow,
} from "@/shared/ui/table"
import type { ProviderConfig } from "@/domains/providers"
import { stripProtocol } from "./providerDisplay"
import { HealthStatus } from "./ProviderHealthStatus"
import { PriorityIndicator } from "./ProviderPriorityControl"
import { ProviderRegistryControls } from "./ProviderRegistryControls"
import { RowPill } from "./ProviderRowPill"

interface ProviderRegistryRowProps {
  provider: ProviderConfig
  rank: number
  providerCount: number
  testing: boolean
  accessPending: boolean
  canMoveUp: boolean
  canMoveDown: boolean
  /** False for a role without control-edit access: read-only values only. */
  canEdit: boolean
  onMovePriority: (direction: "up" | "down") => void
  onToggleGlobal: (enabled: boolean) => void
  onToggleSearch: (enabled: boolean) => void
  onToggleFetch: (enabled: boolean) => void
  onOpenTest: () => void
}

export const ProviderRegistryRow: React.FC<ProviderRegistryRowProps> = ({
  provider,
  rank,
  providerCount,
  testing,
  accessPending,
  canMoveUp,
  canMoveDown,
  canEdit,
  onMovePriority,
  onToggleGlobal,
  onToggleSearch,
  onToggleFetch,
  onOpenTest,
}) => {
  const health = provider.circuitBreaker === "open" ? "open" : provider.healthStatus

  return (
    <TableRow className="border-b border-[var(--border-subtle)] last:border-b-0 hover:bg-[var(--elevated)]">
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <div className="flex items-center gap-3">
          <PriorityIndicator
            provider={provider}
            rank={rank}
            providerCount={providerCount}
            canMoveUp={canMoveUp}
            canMoveDown={canMoveDown}
            canEdit={canEdit}
            onMovePriority={onMovePriority}
          />
          <div className="flex items-center gap-2">
            <ProviderLogo providerId={provider.id} />
            <span className="font-medium text-[var(--text-strong)]">{provider.name}</span>
            {provider.isCustom && <RowPill tone="signal">custom</RowPill>}
            {provider.capabilities.includes("keyless_tier") && (
              <RowPill tone="healthy">keyless</RowPill>
            )}
          </div>
        </div>
      </TableCell>
      <TableCell className="max-w-[250px] whitespace-nowrap px-3 py-2.5">
        <span className="block truncate font-mono text-[12px] text-[var(--muted)]" title={provider.baseUrl}>
          {stripProtocol(provider.baseUrl)}
        </span>
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <HealthStatus status={health} />
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        {canEdit ? (
          <Button
            variant="ghost"
            size="icon-sm"
            type="button"
            onClick={onOpenTest}
            disabled={testing}
            aria-label={`${provider.name} test connection`}
            title={`Test ${provider.name} connection`}
          >
            <RefreshCw aria-hidden="true" className={`size-3.5 ${testing ? "animate-spin" : ""}`} />
          </Button>
        ) : (
          <span className="text-[12px] text-[var(--muted)]" title="Read-only for your role">
            Hidden
          </span>
        )}
      </TableCell>
      <ProviderRegistryControls
        provider={provider}
        canEdit={canEdit}
        accessPending={accessPending}
        onToggleGlobal={onToggleGlobal}
        onToggleSearch={onToggleSearch}
        onToggleFetch={onToggleFetch}
      />
    </TableRow>
  )
}
