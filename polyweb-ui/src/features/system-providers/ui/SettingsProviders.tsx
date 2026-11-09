import React, { useEffect, useState } from "react"
import { usePolyweb } from "@/context/usePolyweb"
import { TooltipProvider } from "@/shared/ui/tooltip"
import { Table, TableBody } from "@/shared/ui/table"
import type { ProviderTestResult, TimedTestResult } from "./providerDisplay"
import { ProviderRegistryHeader } from "./ProviderRegistryHeader"
import { ProviderRegistryRow } from "./ProviderRegistryRow"
import { ProviderTestModal } from "./ProviderTestModal"
import { SettingsFailover } from "./SettingsFailover"

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
  testConnection: (id: string) => Promise<ProviderTestResult>,
) {
  const [testingId, setTestingId] = useState<string | null>(null)
  const [selectedTestId, setSelectedTestId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, TimedTestResult>>({})

  const handleTest = async (id: string) => {
    setTestingId(id)
    try {
      const result = await testConnection(id)
      setTestResults((prev) => ({ ...prev, [id]: { ...result, checkedAt: Date.now() } }))
    } finally {
      setTestingId(null)
    }
  }

  return { testingId, selectedTestId, setSelectedTestId, testResults, handleTest }
}

/** The current time, refreshed once a minute so relative times stay true. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

/**
 * Provider catalog: identity, endpoint, costs, the last connection test,
 * per-operation switches and the master Enabled switch, in one table; the
 * installation's fallback policy sits under it.
 */
export const SettingsProviders: React.FC = () => {
  const {
    providers,
    providersError,
    canEditControls,
    toggleProvider,
    toggleProviderSearch,
    toggleProviderFetch,
    testProviderConnection,
  } = usePolyweb()
  const { pendingProviderIds, handleFlagToggle } = useFlagToggle()
  const { testingId, selectedTestId, setSelectedTestId, testResults, handleTest } =
    useProviderTester(testProviderConnection)
  const now = useNow()
  const catalog = [...providers].sort((a, b) => a.name.localeCompare(b.name))
  const selectedProvider = providers.find((p) => p.id === selectedTestId) ?? null
  const selectedLastResult = selectedProvider ? testResults[selectedProvider.id] : undefined

  return (
    <TooltipProvider delay={100}>
      <section className="w-full max-w-none space-y-8 [--control-on:color-mix(in_srgb,var(--text-strong)_55%,var(--elevated))]">
        {providersError && (
          <p role="alert" className="text-[13px] text-[var(--status-danger)]">
            Providers could not be loaded: {providersError}
          </p>
        )}

        <div className="w-full max-w-none overflow-hidden rounded-lg border border-[var(--border-subtle)]">
          <Table className="min-w-[960px] text-[13px]">
            <ProviderRegistryHeader />
            <TableBody>
              {catalog.map((provider) => (
                <ProviderRegistryRow
                  key={provider.id}
                  provider={provider}
                  testing={testingId === provider.id}
                  lastResult={testResults[provider.id]}
                  now={now}
                  accessPending={pendingProviderIds.has(provider.id)}
                  canEdit={canEditControls}
                  onToggleGlobal={(enabled) => void handleFlagToggle(provider.id, () => toggleProvider(provider.id, enabled))}
                  onToggleSearch={(enabled) => void handleFlagToggle(provider.id, () => toggleProviderSearch(provider.id, enabled))}
                  onToggleFetch={(enabled) => void handleFlagToggle(provider.id, () => toggleProviderFetch(provider.id, enabled))}
                  onOpenTest={() => setSelectedTestId(provider.id)}
                />
              ))}
            </TableBody>
          </Table>
        </div>

        <SettingsFailover />

        {canEditControls && (
          <ProviderTestModal
            provider={selectedProvider}
            testing={selectedProvider ? testingId === selectedProvider.id : false}
            {...(selectedLastResult !== undefined ? { lastResult: selectedLastResult } : {})}
            now={now}
            onClose={() => setSelectedTestId(null)}
            onTest={(id) => void handleTest(id)}
          />
        )}
      </section>
    </TooltipProvider>
  )
}
