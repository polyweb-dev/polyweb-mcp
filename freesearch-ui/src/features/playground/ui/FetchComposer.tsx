import { FileText } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ComposerShell } from "@/components/common/ComposerShell"
import { PillTabsList } from "@/components/common/PillTabs"
import type { PlaygroundController } from "../model/usePlaygroundController"

/**
 * Fetch request form via the shared composer shell. Mounted once per Fetch
 * panel mount so the hero->docked transition keeps the same form/input
 * nodes, value, and focus.
 */
export function FetchComposer({ controller }: { controller: PlaygroundController }) {
  const {
    fetchUrl,
    setFetchUrl,
    selectedProviderId,
    setSelectedProviderId,
    eligibleProviders,
    isSearching,
    isFetching,
    handleExecute,
  } = controller
  return (
    <form onSubmit={handleExecute} className="w-full">
      <ComposerShell
        testIdPrefix="fetch"
        inputRow={
          <div className="relative">
            <div
              className="absolute left-0 top-1/2 -translate-y-1/2 pl-1"
              style={{ color: "var(--muted)" }}
            >
              <FileText className="size-5" />
            </div>
            <input
              type="url"
              value={fetchUrl}
              onChange={(e) => setFetchUrl(e.target.value)}
              placeholder="Enter a URL to fetch and convert..."
              className="w-full bg-transparent py-3 pl-9 pr-32 text-[15px] font-mono outline-none placeholder:text-[var(--muted)]"
              style={{ color: "var(--text-strong)" }}
            />
            <div className="absolute right-0 top-1/2 -translate-y-1/2">
              <Button
                type="submit"
                disabled={isSearching || isFetching}
                className="inline-flex items-center gap-2 rounded-md px-5 py-2 text-[13px] font-medium text-white"
                style={{ background: "var(--signal)" }}
              >
                <FileText aria-hidden="true" className="size-3.5" />
                {isSearching || isFetching ? "Executing..." : "Fetch"}
              </Button>
            </div>
          </div>
        }
        footer={
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <span>Provider:</span>
              <select
                value={selectedProviderId}
                onChange={(e) => setSelectedProviderId(e.target.value)}
                className="rounded border border-[var(--border-subtle)] bg-[var(--elevated)] px-2.5 py-1 text-[13px] text-[var(--text)] outline-none"
              >
                <option value="auto">Auto arbitration</option>
                {eligibleProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </select>
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
        }
      />
    </form>
  )
}
