import { PillTabsList } from "@/shared/ui/PillTabsList"
import { ProviderSelect } from "@/shared/ui/ProviderSelect"
import type { PlaygroundController } from "../model/usePlaygroundController"

const quickQueries = [
  "python async search aggregator",
  "circuit breaker resilience patterns",
  "keenable keyless free tier",
  "react server components streaming",
]

/** The provider field style of the composer footer. */
const providerFieldClass =
  "min-w-48 rounded border border-[var(--border-subtle)] bg-[var(--elevated)] px-2.5 py-1 text-[13px] text-[var(--text)] outline-none"

/**
 * Search footer tray: suggestions plus provider/count controls. Lives inside
 * the composer box so the input row and its options read as one surface.
 */
export function SearchOptions({ controller }: { controller: PlaygroundController }) {
  const { setQuery, selectedProviderId, setSelectedProviderId, eligibleProviders, resultCount, setResultCount } = controller
  const providerOptions = [
    { value: "all", label: "All Providers (Ranked Fusion)" },
    { value: "auto", label: "Auto arbitration" },
    ...eligibleProviders.map((provider) => ({ value: provider.id, label: provider.name })),
  ]
  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span>Suggestions:</span>
        {quickQueries.map((quickQuery) => (
          <button
            key={quickQuery}
            type="button"
            onClick={() => setQuery(quickQuery)}
            className="transition-colors hover:text-[var(--text-strong)] hover:underline"
          >
            {quickQuery}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <label htmlFor="playground-search-provider">Provider:</label>
            <ProviderSelect
              id="playground-search-provider"
              testId="playground-search-provider"
              className={providerFieldClass}
              value={selectedProviderId}
              options={providerOptions}
              onValueChange={setSelectedProviderId}
            />
          </div>

          <label className="flex items-center gap-2">
            <span>Results:</span>
            <input
              type="number"
              aria-label="Number of results"
              min="1"
              max="100"
              step="1"
              value={resultCount}
              onChange={(e) => setResultCount(Number(e.target.value))}
              className="w-16 rounded border border-[var(--border-subtle)] bg-[var(--elevated)] px-2.5 py-1 text-[13px] text-[var(--text)] outline-none tnum"
            />
          </label>
        </div>

        <div
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault()
              e.stopPropagation()
              ;(e.target as HTMLElement)?.click()
            }
          }}
        >
          <PillTabsList />
        </div>
      </div>
    </>
  )
}
