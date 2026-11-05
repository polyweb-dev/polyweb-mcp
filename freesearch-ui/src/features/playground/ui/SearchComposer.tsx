import { Search } from "lucide-react"
import { Button } from "@/shared/ui/button"
import type { PlaygroundController } from "../model/usePlaygroundController"
import { SearchOptions } from "./SearchOptions"

/**
 * Search request form: elevated composer box with the input row on top and
 * the options tray below the divider. Mounted once per Search panel mount so
 * the hero->docked transition keeps the same form/input nodes, value, and
 * focus.
 */
export function SearchComposer({ controller }: { controller: PlaygroundController }) {
  const { mode, query, setQuery, isSearching, isFetching, handleExecute } = controller
  return (
    <form onSubmit={handleExecute} noValidate={mode === "search"} className="w-full">
      {/* Search composer seam; Fetch and Simulator can adopt the pattern later. */}
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
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search the web"
            className="w-full bg-transparent py-3 pl-9 pr-32 text-[15px] font-mono outline-none placeholder:text-[var(--muted)]"
            style={{ color: "var(--text-strong)" }}
          />
          <div className="absolute right-0 top-1/2 -translate-y-1/2">
            <Button
              type="submit"
              formNoValidate
              disabled={isSearching || isFetching || controller.noProviderForMode}
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
          <SearchOptions controller={controller} />
        </div>
      </div>
    </form>
  )
}
