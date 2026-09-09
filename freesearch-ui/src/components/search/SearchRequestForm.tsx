import { Search } from "lucide-react"
import {
  PillTabsList,
} from "@/components/common/PillTabs"
import { Button } from "@/components/ui/button"
import { ProviderPicker } from "./ProviderPicker"
import type { ProviderConfig } from "@/types/freesearch"
import type { FormEvent } from "react"

const QUICK_QUERIES = [
  "python async search aggregator",
  "circuit breaker resilience patterns",
  "keenable keyless free tier",
  "react server components streaming",
]

type SearchRequestFormOptions = {
  query: string
  isSearching: boolean
  isFetching: boolean
  eligibleProviders: ProviderConfig[]
  selectedProviderId: string
  resultCount: number
  onSubmit: (event?: FormEvent) => void | Promise<void>
  onQueryChange: (query: string) => void
  onProviderChange: (providerId: string) => void
  onResultCountChange: (count: number) => void
}

export function SearchRequestForm({
  query,
  isSearching,
  isFetching,
  eligibleProviders,
  selectedProviderId,
  resultCount,
  onSubmit,
  onQueryChange,
  onProviderChange,
  onResultCountChange,
}: SearchRequestFormOptions) {
  return (
    <form onSubmit={onSubmit} noValidate className="w-full">
      <div
        data-testid="search-composer"
        className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--elevated)] p-4 shadow-lg transition-all transition-colors focus-within:border-[var(--signal)]/60 motion-reduce:transition-none"
      >
        <div className="relative">
          <div
            className="absolute left-0 top-1/2 -translate-y-1/2 pl-1"
            style={{ color: "var(--muted)" }}
          >
            <Search className="size-5" />
          </div>
          <input
            type="text"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Search across all providers..."
            className="w-full bg-transparent py-3 pl-9 pr-32 text-[15px] font-mono outline-none placeholder:text-[var(--muted)]"
            style={{ color: "var(--text-strong)" }}
          />
          <div className="absolute right-0 top-1/2 -translate-y-1/2">
            <Button
              type="submit"
              formNoValidate
              disabled={isSearching || isFetching}
              className="inline-flex items-center gap-2 rounded-md px-5 py-2 text-[13px] font-medium text-white"
              style={{ background: "var(--signal)" }}
            >
              <Search aria-hidden="true" className="size-3.5" />
              {isSearching || isFetching ? "Executing..." : "Search"}
            </Button>
          </div>
        </div>

        <hr
          data-testid="search-composer-divider"
          className="mt-3 border-0 border-t border-[var(--border-subtle)] pt-3"
        />
        <div
          data-testid="search-composer-footer"
          className="space-y-3 text-[13px] text-[var(--muted)]"
        >
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span>Suggestions:</span>
            {QUICK_QUERIES.map((quickQuery) => (
              <button
                key={quickQuery}
                type="button"
                onClick={() => onQueryChange(quickQuery)}
                className="transition-colors hover:text-[var(--text-strong)] hover:underline"
              >
                {quickQuery}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-4">
              <ProviderPicker
                eligibleProviders={eligibleProviders}
                selectedProviderId={selectedProviderId}
                onProviderChange={onProviderChange}
              />

              <label className="flex items-center gap-2">
                <span>Results:</span>
                <input
                  type="number"
                  aria-label="Number of results"
                  min="1"
                  max="100"
                  step="1"
                  value={resultCount}
                  onChange={(e) => onResultCountChange(Number(e.target.value))}
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
        </div>
      </div>
    </form>
  )
}
