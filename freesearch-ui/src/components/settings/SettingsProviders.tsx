import React, { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import type { ProviderConfig } from "@/domains/providers"
import { TooltipProvider } from "@/shared/ui/tooltip"
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/ui/table"
import { ProviderRegistryHeader } from "./ProviderRegistryHeader"
import { ProviderRegistryRow } from "./ProviderRegistryRow"
import { ProviderTestModal } from "./ProviderTestModal"
import { ResiliencePolicy } from "./ResiliencePolicy"
import { TavilyRateTierSelect } from "./TavilyRateTierSelect"
import { useProviderRegistryDnD } from "./useProviderRegistryDnD"

type TestResult = Awaited<ReturnType<ReturnType<typeof useFreeSearch>["testProviderConnection"]>>

function getPriorityMeta<T extends { id: string; priority: number }>(items: readonly T[]) {
  const sorted = [...items].sort((a, b) => a.priority - b.priority)
  return {
    rankById: new Map(sorted.map((item, index) => [item.id, index + 1])),
    firstId: sorted[0]?.id ?? null,
    lastId: sorted.at(-1)?.id ?? null,
  }
}

function useFlagToggle() {
  const [pendingProviderIds, setPendingProviderIds] = useState<ReadonlySet<string>>(new Set())
  const handleFlagToggle = async (id: string, command: () => Promise<void>): Promise<void> => {
    setPendingProviderIds((prev) => new Set(prev).add(id))
    try {
      await command()
    } finally {
      setPendingProviderIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }
  return { pendingProviderIds, handleFlagToggle }
}

function useProviderTester(
  testConnection: (id: string) => Promise<TestResult>,
) {
  const [testingId, setTestingId] = useState<string | null>(null)
  const [selectedTestId, setSelectedTestId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({})

  const handleTest = async (id: string) => {
    setTestingId(id)
    try {
      const result = await testConnection(id)
      setTestResults((prev) => ({ ...prev, [id]: result }))
    } finally {
      setTestingId(null)
    }
  }

  return { testingId, selectedTestId, setSelectedTestId, testResults, handleTest }
}

/** The Tavily-only rate-tier slot; every other provider renders no extra cell. */
function rateTierSlot(
  provider: ProviderConfig,
  canEdit: boolean,
  refreshProviders: () => Promise<void>,
  refreshDashboard: () => Promise<void>,
): React.ReactNode {
  if (provider.id !== "tavily") return undefined
  return (
    <TavilyRateTierSelect
      provider={provider}
      canEdit={canEdit}
      onUpdated={async () => {
        await refreshProviders()
        await refreshDashboard()
      }}
    />
  )
}

/** Registry controls and live fleet telemetry in one operational table. */
export const SettingsProviders: React.FC = () => {
  const {
    providers,
    providersError,
    canEditControls,
    toggleProvider,
    toggleProviderSearch,
    toggleProviderFetch,
    moveProviderPriority,
    reorderProviderPriority,
    testProviderConnection,
    refreshProviders,
    refreshDashboard,
  } = useFreeSearch()
  const { pendingProviderIds, handleFlagToggle } = useFlagToggle()
  const { testingId, selectedTestId, setSelectedTestId, testResults, handleTest } =
    useProviderTester(testProviderConnection)
  const {
    draggingId,
    dragOverId,
    handleDragStart,
    handleDragOver,
    handleDrop,
    handleDragEnd,
  } = useProviderRegistryDnD(reorderProviderPriority)

  const { rankById, firstId, lastId } = getPriorityMeta(providers)
  const selectedProvider = providers.find((p) => p.id === selectedTestId) ?? null
  const selectedLastResult = selectedProvider ? testResults[selectedProvider.id] : undefined

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
          <ProviderRegistryHeader providers={providers} />

          <Table className="min-w-[960px] text-[13px]">
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
                  accessPending={pendingProviderIds.has(provider.id)}
                  canMoveUp={providers.length > 1 && provider.id !== firstId}
                  canMoveDown={providers.length > 1 && provider.id !== lastId}
                  canEdit={canEditControls}
                  rateTier={rateTierSlot(provider, canEditControls, refreshProviders, refreshDashboard)}
                  isDragging={draggingId === provider.id}
                  isDragOver={dragOverId === provider.id}
                  onDragStart={(e) => handleDragStart(provider.id, e)}
                  onDragOver={(e) => handleDragOver(provider.id, e)}
                  onDrop={(e) => void handleDrop(provider.id, e)}
                  onDragEnd={handleDragEnd}
                  onMovePriority={(direction) => moveProviderPriority(provider.id, direction)}
                  onToggleGlobal={(enabled) => void handleFlagToggle(provider.id, () => toggleProvider(provider.id, enabled))}
                  onToggleSearch={(enabled) => void handleFlagToggle(provider.id, () => toggleProviderSearch(provider.id, enabled))}
                  onToggleFetch={(enabled) => void handleFlagToggle(provider.id, () => toggleProviderFetch(provider.id, enabled))}
                  onOpenTest={() => setSelectedTestId(provider.id)}
                />
              ))}
            </TableBody>
          </Table>
        </div>

        <ResiliencePolicy />

        {canEditControls && (
          <ProviderTestModal
            provider={selectedProvider}
            testing={selectedProvider ? testingId === selectedProvider.id : false}
            {...(selectedLastResult !== undefined ? { lastResult: selectedLastResult } : {})}
            onClose={() => setSelectedTestId(null)}
            onTest={(id) => void handleTest(id)}
          />
        )}
      </section>
    </TooltipProvider>
  )
}

const MERGED_HEADERS = [
  "Priority",
  "Provider",
  "Endpoint",
  "Test",
  "Search",
  "Fetch",
  "Global",
] as const
