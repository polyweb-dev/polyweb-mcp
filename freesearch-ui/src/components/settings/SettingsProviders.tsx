import React, { useState } from "react"
import { ArrowDown, ArrowUp, RefreshCw } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { Modal } from "@/components/common/Modal"
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

type TestResult = Awaited<ReturnType<ReturnType<typeof useFreeSearch>["testProviderConnection"]>>

/** Registry controls and live fleet telemetry in one operational table. */
export const SettingsProviders: React.FC = () => {
  const {
    providers,
    providersError,
    toggleProvider,
    toggleProviderSearch,
    toggleProviderFetch,
    moveProviderPriority,
    setCircuitBreaker,
    testProviderConnection,
  } = useFreeSearch()
  const [testingId, setTestingId] = useState<string | null>(null)
  const [pendingGlobalId, setPendingGlobalId] = useState<string | null>(null)
  const [selectedTestId, setSelectedTestId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({})

  const handleGlobalToggle = async (id: string, enabled: boolean) => {
    setPendingGlobalId(id)
    try {
      await toggleProvider(id, enabled)
    } finally {
      setPendingGlobalId(null)
    }
  }

  const handleTest = async (id: string) => {
    setTestingId(id)
    try {
      const result = await testProviderConnection(id)
      setTestResults((previous) => ({ ...previous, [id]: result }))
    } finally {
      setTestingId(null)
    }
  }

  const sortedByPriority = [...providers].sort((a, b) => a.priority - b.priority)
  const rankById = new Map(sortedByPriority.map((provider, index) => [provider.id, index + 1]))
  const firstPriorityId = sortedByPriority[0]?.id ?? null
  const lastPriorityId = sortedByPriority.at(-1)?.id ?? null
  const selectedProvider = providers.find((provider) => provider.id === selectedTestId) ?? null

  return (
    <section className="w-full max-w-none space-y-4">
      <div>
        <h3 className="text-[var(--text-strong)]">Provider registry</h3>
        <p className="mt-0.5 text-[13px] text-[var(--muted)]">
          Reorder dispatch priority, control routing, and inspect live provider telemetry.
        </p>
      </div>

      {providersError && (
        <p
          role="alert"
          className="rounded border border-[var(--status-danger)]/40 bg-[var(--elevated)] p-3 text-[13px]"
          style={{ color: "var(--status-danger)" }}
        >
          Provider data unavailable — {providersError}
        </p>
      )}

      <div className="w-full max-w-none overflow-hidden rounded-lg border border-[var(--border-subtle)]">
        <Table className="min-w-[1280px] text-[13px]">
          <TableHeader>
            <TableRow className="border-b border-[var(--border-subtle)] bg-[var(--elevated)] hover:bg-[var(--elevated)]">
              {MERGED_HEADERS.map((header) => (
                <TableHead key={header} className="h-9 whitespace-nowrap px-3 text-[12px] text-[var(--muted)]">
                  {header}
                </TableHead>
              ))}
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
                canMoveUp={providers.length > 1 && provider.id !== firstPriorityId}
                canMoveDown={providers.length > 1 && provider.id !== lastPriorityId}
                onMovePriority={(direction) => moveProviderPriority(provider.id, direction)}
                onToggleGlobal={(enabled) => void handleGlobalToggle(provider.id, enabled)}
                onToggleSearch={(enabled) => toggleProviderSearch(provider.id, enabled)}
                onToggleFetch={(enabled) => toggleProviderFetch(provider.id, enabled)}
                onToggleBreaker={() =>
                  void setCircuitBreaker(
                    provider.id,
                    provider.circuitBreaker === "open" ? "closed" : "open"
                  )
                }
                onOpenTest={() => setSelectedTestId(provider.id)}
              />
            ))}
          </TableBody>
        </Table>
      </div>

      <ProviderTestModal
        provider={selectedProvider}
        testing={selectedProvider ? testingId === selectedProvider.id : false}
        lastResult={selectedProvider ? testResults[selectedProvider.id] : undefined}
        onClose={() => setSelectedTestId(null)}
        onTest={(id) => void handleTest(id)}
      />
    </section>
  )
}

const MERGED_HEADERS = [
  "Provider",
  "Endpoint",
  "Global",
  "Search",
  "Fetch",
  "Health",
  "p95",
  "Quota",
  "Breaker",
  "Test",
] as const

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
  onToggleBreaker: () => void
  onOpenTest: () => void
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
  onToggleBreaker,
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
        <span className="sr-only">Global</span>
        <Switch
          checked={provider.globalEnabled}
          onChange={onToggleGlobal}
          disabled={globalPending}
          ariaLabel={`${provider.name} global routing`}
        />
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
        <HealthStatus status={health} />
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5 text-right tnum">
        {formatLatency(provider.latencyP95Ms)}
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5 text-right tnum">
        {formatQuota(provider)}
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <Button variant="outline" size="sm" type="button" onClick={onToggleBreaker}>
          {provider.circuitBreaker === "open" ? "Reset" : "Trip"}
        </Button>
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
    </TableRow>
  )
}

export const ProviderTestModal: React.FC<{
  provider: ProviderConfig | null
  testing: boolean
  lastResult?: TestResult
  onClose: () => void
  onTest: (id: string) => void
}> = ({ provider, testing, lastResult, onClose, onTest }) => (
  <Modal
    isOpen={provider !== null}
    onClose={onClose}
    title={provider ? `Test ${provider.name}` : "Test provider"}
    subtitle="Inspect the current provider state before running a connection probe."
    maxWidth="lg"
  >
    {provider && (
      <div className="space-y-4">
        <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-4 gap-y-2 text-[13px]">
          <ModalDetail label="Endpoint" value={stripProtocol(provider.baseUrl)} mono />
          <ModalDetail label="Capabilities" value={provider.capabilities.join(", ")} />
          <ModalDetail label="Health" value={provider.circuitBreaker === "open" ? "open" : provider.healthStatus} />
          <ModalDetail label="p95" value={formatLatency(provider.latencyP95Ms)} />
          <ModalDetail label="Quota" value={formatQuota(provider)} />
          <ModalDetail
            label="Last result"
            value={lastResult ? `${lastResult.success ? "healthy" : lastResult.message} · ${lastResult.latencyMs}ms` : "Not tested"}
          />
        </dl>
        <div className="flex justify-end border-t border-[var(--border-subtle)] pt-4">
          <Button type="button" onClick={() => onTest(provider.id)} disabled={testing}>
            {testing ? "Testing..." : "Test"}
          </Button>
        </div>
      </div>
    )}
  </Modal>
)

const ModalDetail: React.FC<{ label: string; value: string; mono?: boolean }> = ({
  label,
  value,
  mono = false,
}) => (
  <>
    <dt className="text-[var(--muted)]">{label}</dt>
    <dd className={`min-w-0 break-words text-[var(--text-strong)] ${mono ? "font-mono text-[12px]" : ""}`}>
      {value}
    </dd>
  </>
)

const HealthStatus: React.FC<{ status: string }> = ({ status }) => {
  const color = status === "healthy"
    ? "var(--status-healthy)"
    : status === "open" || status === "circuit_broken"
      ? "var(--status-danger)"
      : "var(--status-warning)"

  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--muted)]">
      <span aria-hidden="true" className="size-2 rounded-full" style={{ background: color }} />
      {status.replace("_", " ")}
    </span>
  )
}

const stripProtocol = (url: string) => url.replace(/^https?:\/\//, "")
const formatLatency = (latency: number | null) => latency === null ? "—" : `${latency}ms`
const formatQuota = (provider: ProviderConfig) => `${provider.quota.used ?? "—"}/${provider.quota.limit ?? "∞"}`

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
      className="text-[var(--muted)] transition-colors hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 disabled:cursor-not-allowed disabled:opacity-30 motion-reduce:transition-none"
    >
      <ArrowUp className="size-3" />
    </button>
    <span className="text-[12px] leading-none text-[var(--muted)] tnum" title={`Dispatch order ${rank} of ${providerCount}`}>
      P{rank}
    </span>
    <button
      type="button"
      aria-label={`Move ${provider.name} priority down`}
      onClick={() => onMovePriority("down")}
      disabled={!canMoveDown}
      className="text-[var(--muted)] transition-colors hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 disabled:cursor-not-allowed disabled:opacity-30 motion-reduce:transition-none"
    >
      <ArrowDown className="size-3" />
    </button>
  </div>
)

const RowPill: React.FC<{ tone: "signal" | "healthy"; children: React.ReactNode }> = ({ tone, children }) => (
  <span
    className="whitespace-nowrap rounded px-1.5 py-0.5 text-[12px]"
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
    return globallyDisabled ? (
      <span className="inline-flex min-w-[110px] text-[var(--muted)] opacity-60">—</span>
    ) : (
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
