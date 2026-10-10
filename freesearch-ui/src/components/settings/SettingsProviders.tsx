import React, { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
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

type TestResult = Awaited<ReturnType<ReturnType<typeof useFreeSearch>["testProviderConnection"]>>

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
    testProviderConnection,
  } = useFreeSearch()
  const [testingId, setTestingId] = useState<string | null>(null)
  const [pendingProviderIds, setPendingProviderIds] = useState<ReadonlySet<string>>(new Set())
  const [selectedTestId, setSelectedTestId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({})

  const handleFlagToggle = async (id: string, command: () => Promise<void>): Promise<void> => {
    setPendingProviderIds((previous) => new Set(previous).add(id))
    try {
      await command()
    } finally {
      setPendingProviderIds((previous) => {
        const next = new Set(previous)
        next.delete(id)
        return next
      })
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
                  canMoveUp={providers.length > 1 && provider.id !== firstPriorityId}
                  canMoveDown={providers.length > 1 && provider.id !== lastPriorityId}
                  canEdit={canEditControls}
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
  "Provider",
  "Endpoint",
  "Health",
  "Test",
  "Search",
  "Fetch",
  "Global",
] as const
