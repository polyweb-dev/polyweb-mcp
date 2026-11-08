import { ProviderSelect } from "@/shared/ui/ProviderSelect"
import { Button } from "@/shared/ui/button"
import type { PlaygroundController } from "../model/usePlaygroundController"

const quickQueries = [
  "python async search aggregator",
  "circuit breaker resilience patterns",
  "keenable keyless free tier",
]

/** The provider field style of the composer footer. */
const providerFieldClass =
  "min-w-48 rounded border border-[var(--border-subtle)] bg-[var(--elevated)] px-2.5 py-1 text-[13px] text-[var(--text)] outline-none"

/**
 * Search footer tray: suggestion chips, then the provider and result-count
 * controls. Lives inside the composer box so the input row and its options
 * read as one surface.
 */
export function SearchOptions({ controller }: { controller: PlaygroundController }) {
  const { setQuery, selectedProviderId, setSelectedProviderId, eligibleProviders, resultCount, setResultCount } = controller
  const providerOptions = [
    { value: "auto", label: "Auto" },
    { value: "all", label: "All providers" },
    ...eligibleProviders.map((provider) => ({ value: provider.id, label: provider.name })),
  ]
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1">Suggestions</span>
        {quickQueries.map((quickQuery) => (
          <Button
            key={quickQuery}
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setQuery(quickQuery)}
            className="rounded-full border border-[var(--border-subtle)] px-2.5 font-normal text-[var(--muted)] hover:text-[var(--text-strong)]"
          >
            {quickQuery}
          </Button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-6">
        {controller.providersError && (
          <span role="alert" className="flex items-center gap-2 text-[var(--status-danger)]">
            Couldn't load this project's providers.
            <Button
              type="button"
              size="form"
              variant="outline"
              onClick={() => controller.retryProviders()}
            >
              Retry
            </Button>
          </span>
        )}
        <div className="flex items-center gap-2">
          <label htmlFor="playground-search-provider">Provider</label>
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
          <span>Results</span>
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
    </>
  )
}
