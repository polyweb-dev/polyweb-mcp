import React, { useState } from "react"
import { ArrowDown, ArrowUp } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { Switch } from "@/components/common/Switch"
import { SegmentedControl } from "@/components/common/SegmentedControl"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { ProviderConfig } from "@/types/freesearch"

/**
 * Provider registry: dispatch priority, global and per-operation routing
 * switches, and connection tests. Providers are added or removed upstream —
 * this registry only reconfigures them.
 */
export const SettingsProviders: React.FC = () => {
  const {
    providers,
    toggleProvider,
    toggleProviderSearch,
    toggleProviderFetch,
    moveProviderPriority,
    testProviderConnection,
  } = useFreeSearch()
  const [testingId, setTestingId] = useState<string | null>(null)
  const [pendingGlobalId, setPendingGlobalId] = useState<string | null>(null)

  const handleGlobalToggle = async (id: string, enabled: boolean) => {
    setPendingGlobalId(id)
    try {
      await toggleProvider(id, enabled)
    } finally {
      setPendingGlobalId(null)
    }
  }

  // Priority boundaries come from the sorted order, not the render order.
  const sortedByPriority = [...providers].sort((a, b) => a.priority - b.priority)
  const rankById = new Map(
    sortedByPriority.map((provider, index) => [provider.id, index + 1])
  )
  const firstPriorityId = sortedByPriority[0]?.id ?? null
  const lastPriorityId = sortedByPriority[sortedByPriority.length - 1]?.id ?? null
  const singleRow = providers.length < 2

  const handleTest = async (id: string) => {
    setTestingId(id)
    try {
      await testProviderConnection(id)
    } finally {
      setTestingId(null)
    }
  }

  return (
    <section className="space-y-4 max-w-4xl">
      <div>
        <h3 className="text-[var(--text-strong)]">Provider registry</h3>
        <p className="text-[13px] text-[var(--muted)] mt-0.5">
          Reorder dispatch priority and toggle global, search, or fetch routing.
        </p>
      </div>

      <div className="overflow-hidden rounded-lg border border-[var(--border-subtle)]">
        <Table className="min-w-[880px] text-[13px]">
          <TableHeader>
            <TableRow className="border-b border-[var(--border-subtle)] bg-[var(--elevated)] hover:bg-[var(--elevated)]">
              <TableHead className="h-9 px-3 text-[12px] text-[var(--muted)]">Provider</TableHead>
              <TableHead className="h-9 w-[110px] px-3 text-[12px] text-[var(--muted)]">
                Global
              </TableHead>
              <TableHead className="h-9 w-[170px] px-3 text-[12px] text-[var(--muted)]">
                Search
              </TableHead>
              <TableHead className="h-9 w-[170px] px-3 text-[12px] text-[var(--muted)]">
                Fetch
              </TableHead>
              <TableHead className="h-9 w-20 px-3 text-[12px] text-[var(--muted)]">
                Test
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {providers.map((provider) => (
              <ProviderRegistryRow
                key={provider.id}
                provider={provider}
                rank={rankById.get(provider.id) ?? 0}
                providerCount={providers.length}
                testing={testingId === provider.id}
                globalPending={pendingGlobalId === provider.id}
                canMoveUp={!singleRow && provider.id !== firstPriorityId}
                canMoveDown={!singleRow && provider.id !== lastPriorityId}
                onMovePriority={(direction) => moveProviderPriority(provider.id, direction)}
                onToggleGlobal={(enabled) => void handleGlobalToggle(provider.id, enabled)}
                onToggleSearch={(enabled) => toggleProviderSearch(provider.id, enabled)}
                onToggleFetch={(enabled) => toggleProviderFetch(provider.id, enabled)}
                onTest={() => handleTest(provider.id)}
              />
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  )
}

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
  onTest: () => void
}

const ProviderRegistryRow: React.FC<ProviderRegistryRowProps> = ({
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
  onTest,
}) => {
  const supportsSearch = provider.capabilities.includes("search")
  const supportsFetch = provider.capabilities.includes("fetch")

  return (
    <TableRow className="border-b border-[var(--border-subtle)] last:border-b-0 hover:bg-[var(--elevated)]">
      <TableCell className="px-3 py-2.5">
        <div className="flex items-center gap-3">
          <PriorityIndicator
            provider={provider}
            rank={rank}
            providerCount={providerCount}
            canMoveUp={canMoveUp}
            canMoveDown={canMoveDown}
            onMovePriority={onMovePriority}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium text-[var(--text-strong)]">{provider.name}</span>
              {provider.isCustom && <RowPill tone="signal">custom</RowPill>}
              {provider.capabilities.includes("keyless_tier") && (
                <RowPill tone="healthy">keyless</RowPill>
              )}
            </div>
            <span className="block truncate text-[12px] text-[var(--muted)]">
              {provider.capabilities.join(", ")}
            </span>
          </div>
        </div>
      </TableCell>
      <TableCell className="w-[110px] px-3 py-2.5">
        <span className="sr-only">Global</span>
        <Switch
          checked={provider.globalEnabled}
          onChange={onToggleGlobal}
          disabled={globalPending}
          ariaLabel={`${provider.name} global routing`}
        />
      </TableCell>
      <TableCell className="w-[170px] px-3 py-2.5">
        <OperationControl
          label="Search"
          providerName={provider.name}
          supported={supportsSearch}
          enabled={provider.searchEnabled}
          globallyDisabled={!provider.globalEnabled}
          onToggle={onToggleSearch}
        />
      </TableCell>
      <TableCell className="w-[170px] px-3 py-2.5">
        <OperationControl
          label="Fetch"
          providerName={provider.name}
          supported={supportsFetch}
          enabled={provider.fetchEnabled}
          globallyDisabled={!provider.globalEnabled}
          onToggle={onToggleFetch}
        />
      </TableCell>
      <TableCell className="w-20 px-3 py-2.5">
        <Button
          variant="outline"
          size="sm"
          type="button"
          onClick={onTest}
          disabled={testing}
          aria-label={`${provider.name} connection`}
        >
          {testing ? "Testing..." : "Test"}
        </Button>
      </TableCell>
    </TableRow>
  )
}

const PriorityIndicator: React.FC<{
  provider: ProviderConfig
  rank: number
  providerCount: number
  canMoveUp: boolean
  canMoveDown: boolean
  onMovePriority: (direction: "up" | "down") => void
}> = ({ provider, rank, providerCount, canMoveUp, canMoveDown, onMovePriority }) => (
  <div className="flex min-w-6 shrink-0 flex-col items-center gap-0.5">
    <button
      type="button"
      aria-label={`Move ${provider.name} priority up`}
      onClick={() => onMovePriority("up")}
      disabled={!canMoveUp}
      className="text-[var(--muted)] hover:text-[var(--text-strong)] transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:text-[var(--muted)]"
    >
      <ArrowUp className="size-3" />
    </button>
    <span
      className="text-[12px] text-[var(--muted)] tnum leading-none"
      title={`Dispatch order ${rank} of ${providerCount}`}
    >
      P{rank}
    </span>
    <button
      type="button"
      aria-label={`Move ${provider.name} priority down`}
      onClick={() => onMovePriority("down")}
      disabled={!canMoveDown}
      className="text-[var(--muted)] hover:text-[var(--text-strong)] transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:text-[var(--muted)]"
    >
      <ArrowDown className="size-3" />
    </button>
  </div>
)

const RowPill: React.FC<{ tone: "signal" | "healthy"; children: React.ReactNode }> = ({
  tone,
  children,
}) => (
  <span
    className="text-[12px] px-1.5 py-0.5 rounded whitespace-nowrap"
    style={{
      background: tone === "signal" ? "var(--signal-muted)" : "rgba(34, 197, 94, 0.1)",
      color: tone === "signal" ? "var(--signal)" : "var(--status-healthy)",
    }}
  >
    {children}
  </span>
)

interface OperationControlProps {
  label: "Search" | "Fetch"
  providerName: string
  supported: boolean
  enabled: boolean
  globallyDisabled: boolean
  onToggle: (enabled: boolean) => void
}

const OperationControl: React.FC<OperationControlProps> = ({
  label,
  providerName,
  supported,
  enabled,
  globallyDisabled,
  onToggle,
}) => {
  if (!supported) {
    if (globallyDisabled) {
      return <span className="inline-flex min-w-[110px] text-[var(--muted)] opacity-60">—</span>
    }
    return (
      <span className="inline-flex min-w-[110px] justify-center rounded border border-[var(--border-subtle)] px-1.5 py-0.5 text-[12px] text-[var(--muted)]">
        Not supported
      </span>
    )
  }

  return (
    <div className="min-w-[110px]" title="Session-only — backend has global enable only">
      <span className="sr-only">{label}</span>
      <fieldset disabled={globallyDisabled} className="m-0 border-0 p-0">
        <SegmentedControl
          options={["On", "Off"] as const}
          value={enabled ? "On" : "Off"}
          onChange={(value) => onToggle(value === "On")}
          ariaLabel={`${providerName} ${label.toLowerCase()} routing`}
          minColumnWidth="52px"
        />
      </fieldset>
    </div>
  )
}
