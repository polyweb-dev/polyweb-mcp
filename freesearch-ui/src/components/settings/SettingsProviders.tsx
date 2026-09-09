import React, { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { TooltipProvider } from "@/components/ui/tooltip"
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { TestResult } from "./providers/shared"
import { ProviderRegistryRow } from "./providers/ProviderRegistryRow"
import { ProviderTestModal } from "./providers/ProviderTestModal"

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

export { ProviderRegistryRow } from "./providers/ProviderRegistryRow"
export { OperationControl } from "./providers/OperationControl"
export { ProviderTestModal } from "./providers/ProviderTestModal"
export { ModalDetail } from "./providers/ModalDetail"
export { HealthStatus } from "./providers/HealthStatus"
export { PriorityIndicator } from "./providers/PriorityIndicator"
export { RowPill } from "./providers/RowPill"
