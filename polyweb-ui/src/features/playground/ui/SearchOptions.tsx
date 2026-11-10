import { useState } from "react"
import { clampLimit } from "@/domains/execution"
import { ProviderSelect } from "@/shared/ui/ProviderSelect"
import { Button } from "@/shared/ui/button"
import { NumericField } from "@/shared/ui/NumericField"
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
  /**
   * The input holds a draft string so it can be cleared naturally: a blank
   * stays visibly blank, while the store always keeps a valid committed
   * value — so submit (by click or by Enter, with or without a blur) always
   * sends a sensible clamped limit. Typing a value commits its clamp at
   * once; blur on a blank exits edit mode, revealing the committed floor.
   */
  const [draft, setDraft] = useState<string | null>(null)
  // Derive the shown value at render: a draft is preserved when it either is
  // a blank in-progress edit or still matches the committed value; upstream
  // moves (rehydration, another setter) rebase automatically without an
  // effect or a cascading render.
  const shown = draft !== null && (draft.trim() === "" || Number(draft) === resultCount)
    ? draft
    : String(resultCount)
  const commit = (raw: string) => {
    if (raw.trim() === "") {
      // Blank stays visible as an in-progress edit; the store keeps the
      // clamp floor so any submit is sensible, matching an explicit 0 → 1.
      setDraft("")
      setResultCount(clampLimit(Number(raw)))
      return
    }
    const value = clampLimit(Number(raw))
    setDraft(String(value))
    setResultCount(value)
  }
  const blur = () => {
    // A blank loses focus: exit edit mode and reveal the committed value.
    setDraft(null)
  }
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

        <div className="flex items-center gap-2 [&>div]:w-16 [&_label]:sr-only">
          <span>Results</span>
          <NumericField
            id="playground-result-count"
            label="Number of results"
            min={1}
            step={1}
            value={shown}
            onChange={commit}
            onBlur={blur}
          />
        </div>
      </div>
    </>
  )
}
