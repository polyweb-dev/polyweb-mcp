import React from "react"
import { RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { Switch } from "@/components/common/Switch"
import { TableCell, TableRow } from "@/components/ui/table"
import type { ProviderConfig } from "@/types/freesearch"
import { HealthStatus } from "./HealthStatus"
import { OperationControl } from "./OperationControl"
import { PriorityIndicator } from "./PriorityIndicator"
import { RowPill } from "./RowPill"
import { formatLatency, formatQuota, stripProtocol } from "./shared"

interface ProviderRegistryRowProps {
  provider: ProviderConfig
  rank: number
  providerCount: number
  testing: boolean
  globalPending: boolean
  canMoveUp: boolean
  canMoveDown: boolean
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
  globalPending,
  canMoveUp,
  canMoveDown,
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
      <TableCell className="whitespace-nowrap px-3 py-2.5 tnum">
        {formatQuota(provider)}
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5 tnum">
        {formatLatency(provider.latencyP95Ms)}
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
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
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <OperationControl
          label="Search"
          providerName={provider.name}
          supported={provider.capabilities.includes("search")}
          enabled={provider.searchEnabled}
          globallyDisabled={!provider.globalEnabled}
          onToggle={onToggleSearch}
        />
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <OperationControl
          label="Fetch"
          providerName={provider.name}
          supported={provider.capabilities.includes("fetch")}
          enabled={provider.fetchEnabled}
          globallyDisabled={!provider.globalEnabled}
          onToggle={onToggleFetch}
        />
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <span className="sr-only">Global</span>
        <Switch
          checked={provider.globalEnabled}
          onChange={onToggleGlobal}
          disabled={globalPending}
          ariaLabel={`${provider.name} global routing`}
        />
      </TableCell>
    </TableRow>
  )
}
