import { Search } from "lucide-react"
import { Button } from "@/shared/ui/button"
import type { PlaygroundController } from "../model/usePlaygroundController"
import { PlaygroundModeTabs } from "./PlaygroundModeTabs"
import { SearchOptions } from "./SearchOptions"

/**
 * Search request form: elevated composer box. The input row reads left to
 * right as mode (Search | Fetch), query, then the primary submit; the options
 * tray sits below the divider. The form keeps its position, value, and focus
 * while results load.
 */
export function SearchComposer({ controller }: { controller: PlaygroundController }) {
  const { mode, query, setQuery, isSearching, isFetching, handleExecute } = controller
  return (
    <form onSubmit={handleExecute} noValidate={mode === "search"} className="w-full">
      <div
        data-testid="search-composer"
        className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--elevated)] p-4 shadow-lg transition-colors motion-reduce:transition-none"
      >
        <div className="flex min-w-0 items-center gap-3">
          <PlaygroundModeTabs />
          <div className="relative min-w-0 flex-1">
            <div
              className="absolute left-0 top-1/2 -translate-y-1/2 pl-1"
              style={{ color: "var(--muted)" }}
            >
              <Search aria-hidden="true" className="size-4" />
            </div>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search the web"
              aria-label="Search query"
              className="w-full rounded-md bg-transparent py-3 pl-8 pr-32 text-[15px] outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--signal)]/40 placeholder:text-[var(--muted)]"
              style={{ color: "var(--text-strong)" }}
            />
            <div className="absolute right-0 top-1/2 -translate-y-1/2">
              <Button
                type="submit"
                formNoValidate
                disabled={isSearching || isFetching || controller.noProviderForMode}
                size="form"
                className="gap-2 px-4"
              >
                <Search aria-hidden="true" className="size-3.5" />
                {isSearching || isFetching ? "Executing..." : "Search"}
              </Button>
            </div>
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
          <SearchOptions controller={controller} />
        </div>
      </div>
    </form>
  )
}
