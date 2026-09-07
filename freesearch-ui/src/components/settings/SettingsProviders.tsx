import React, { useState } from "react"
import { ArrowDown, ArrowUp } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { Switch } from "@/components/common/Switch"
import { SegmentedControl } from "@/components/common/SegmentedControl"
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

      <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
        {providers.map((provider) => (
          <ProviderRegistryRow
            key={provider.id}
            provider={provider}
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
      </div>
    </section>
  )
}

interface ProviderRegistryRowProps {
  provider: ProviderConfig
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
    <div className="p-3 border-b last:border-b-0 border-[var(--border-subtle)] hover:bg-[var(--elevated)] transition-colors">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <PriorityIndicator
          provider={provider}
          canMoveUp={canMoveUp}
          canMoveDown={canMoveDown}
          onMovePriority={onMovePriority}
        />

        <div className="min-w-0 flex-1 basis-48">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium text-[var(--text-strong)]">
              {provider.name}
            </span>
            {provider.isCustom && <RowPill tone="signal">custom</RowPill>}
            {provider.capabilities.includes("keyless_tier") && (
              <RowPill tone="healthy">keyless</RowPill>
            )}
          </div>
          <span className="text-[12px] text-[var(--muted)] block truncate">
            {provider.capabilities.join(", ")}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex items-center gap-1.5">
            <span className="text-[13px] text-[var(--muted)]">Global</span>
            <Switch
              checked={provider.globalEnabled}
              onChange={onToggleGlobal}
              disabled={globalPending}
              ariaLabel={`${provider.name} global routing`}
            />
          </div>

          <OperationControl
            label="Search"
            providerName={provider.name}
            supported={supportsSearch}
            enabled={provider.searchEnabled}
            globallyDisabled={!provider.globalEnabled}
            onToggle={onToggleSearch}
          />
          <OperationControl
            label="Fetch"
            providerName={provider.name}
            supported={supportsFetch}
            enabled={provider.fetchEnabled}
            globallyDisabled={!provider.globalEnabled}
            onToggle={onToggleFetch}
          />

          <button
            type="button"
            onClick={onTest}
            disabled={testing}
            aria-label={`${provider.name} connection`}
            className="text-[13px] text-[var(--muted)] hover:text-white transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
          >
            {testing ? "Testing..." : "Test"}
          </button>
        </div>
      </div>
    </div>
  )
}

const PriorityIndicator: React.FC<{
  provider: ProviderConfig
  canMoveUp: boolean
  canMoveDown: boolean
  onMovePriority: (direction: "up" | "down") => void
}> = ({ provider, canMoveUp, canMoveDown, onMovePriority }) => (
  <div className="flex flex-col items-center gap-0.5 shrink-0">
    <button
      type="button"
      aria-label={`Move ${provider.name} priority up`}
      onClick={() => onMovePriority("up")}
      disabled={!canMoveUp}
      className="text-[var(--muted)] hover:text-[var(--text-strong)] transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:text-[var(--muted)]"
    >
      <ArrowUp className="size-3" />
    </button>
    <span className="text-[12px] text-[var(--muted)] tnum leading-none">P{provider.priority}</span>
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
    // An unsupported operation is only actionable while global routing is on.
    if (globallyDisabled) return null
    return (
      <span className="text-[12px] px-1.5 py-0.5 rounded border border-[var(--border-subtle)] text-[var(--muted)]">
        Not supported
      </span>
    )
  }

  return (
    <div
      className="flex items-center gap-1.5"
      title="Session-only — backend has global enable only"
    >
      <span className="text-[13px] text-[var(--muted)]">{label}</span>
      <fieldset disabled={globallyDisabled} className="min-w-0 border-0 p-0 m-0">
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
