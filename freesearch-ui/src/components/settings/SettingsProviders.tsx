import React, { useState } from "react"
import { ArrowDown, ArrowUp, RefreshCw } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { Modal } from "@/components/common/Modal"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { Switch } from "@/components/common/Switch"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
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

  const activeCount = providers.filter((p) => p.globalEnabled).length
  const healthyCount = providers.filter((p) => p.healthStatus === "healthy" && p.circuitBreaker !== "open").length

  return (
    <TooltipProvider delay={100}>
      <section className="w-full max-w-none space-y-4">
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
          <div className="flex flex-col gap-2 border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2.5">
              <h3 className="text-[13px] font-semibold text-[var(--text-strong)]">Provider registry</h3>
              <span className="rounded-full border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-0.5 text-[11px] text-[var(--muted)] tnum">
                {providers.length} configured
              </span>
              <span className="inline-flex items-center gap-1.5 text-[11px] text-[var(--status-healthy)]">
                <span aria-hidden="true" className="size-1.5 rounded-full bg-[#22c55e]" />
                <span className="tnum">{activeCount} active</span>
              </span>
            </div>
            <div className="flex items-center gap-3 text-[12px] text-[var(--muted)]">
              <span className="hidden sm:inline">Priority dispatch · P1 to P{providers.length}</span>
              <span className="hidden md:inline opacity-40">|</span>
              <span>
                <strong className="font-medium text-[var(--text-strong)] tnum">{healthyCount}/{providers.length}</strong> healthy
              </span>
            </div>
          </div>

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
    </TooltipProvider>
  )
}

const MERGED_HEADERS = [
  "Provider",
  "Endpoint",
  "Health",
  "Quota",
  "p95",
  "Test",
  "Search",
  "Fetch",
  "Global",
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

const HEALTH_CONFIG: Record<
  string,
  { label: string; dotClass: string; textClass: string; bgClass: string }
> = {
  healthy: {
    label: "Healthy",
    dotClass: "bg-[#22c55e]",
    textClass: "text-[#22c55e]",
    bgClass: "bg-[#22c55e]/15",
  },
  offline: {
    label: "Offline",
    dotClass: "bg-[#eab308]",
    textClass: "text-[#eab308]",
    bgClass: "bg-[#eab308]/15",
  },
  degraded: {
    label: "Degraded",
    dotClass: "bg-[#f59e0b]",
    textClass: "text-[#f59e0b]",
    bgClass: "bg-[#f59e0b]/15",
  },
  rate_limited: {
    label: "Rate limited",
    dotClass: "bg-[#f97316]",
    textClass: "text-[#f97316]",
    bgClass: "bg-[#f97316]/15",
  },
  circuit_broken: {
    label: "Circuit broken",
    dotClass: "bg-[#ef4444]",
    textClass: "text-[#ef4444]",
    bgClass: "bg-[#ef4444]/15",
  },
  open: {
    label: "Open",
    dotClass: "bg-[#ef4444]",
    textClass: "text-[#ef4444]",
    bgClass: "bg-[#ef4444]/15",
  },
}

const HealthStatus: React.FC<{ status: string }> = ({ status }) => {
  const config = HEALTH_CONFIG[status] ?? {
    label: status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    dotClass: "bg-[var(--muted)]",
    textClass: "text-[var(--muted)]",
    bgClass: "bg-white/[0.06]",
  }

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-[12px] font-medium ${config.bgClass} ${config.textClass}`}
    >
      <span aria-hidden="true" className={`size-2 rounded-full ${config.dotClass}`} />
      <span>{config.label}</span>
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
    return (
      <Tooltip>
        <TooltipTrigger
          render={<span className="inline-flex cursor-not-allowed" />}
        >
          <Switch
            checked={false}
            onChange={() => {}}
            disabled
            ariaLabel={`${providerName} ${label.toLowerCase()} routing (not supported)`}
          />
        </TooltipTrigger>
        <TooltipContent>
          {providerName} does not support {label.toLowerCase()}
        </TooltipContent>
      </Tooltip>
    )
  }

  return (
    <div title="Session-only — backend has global enable only">
      <Switch
        checked={enabled}
        onChange={onToggle}
        disabled={globallyDisabled}
        ariaLabel={`${providerName} ${label.toLowerCase()} routing`}
      />
    </div>
  )
}
