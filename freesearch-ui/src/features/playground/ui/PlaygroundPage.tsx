import {
  PillTabs,
  PillTabsPanel,
} from "@/components/common/PillTabs"
import { usePlaygroundController } from "../model/usePlaygroundController"
import { FetchSection } from "./FetchSection"
import { SearchSection } from "./SearchSection"

const PLAYGROUND_VIEW_OPTIONS = [
  { value: "search", label: "Search" },
  { value: "fetch", label: "Fetch" },
] as const

/** Search playground page: Search/Fetch pill views over one controller. */
export function PlaygroundPage() {
  const controller = usePlaygroundController()
  return (
    <PillTabs
      options={PLAYGROUND_VIEW_OPTIONS}
      value={controller.mode}
      onValueChange={(value) => controller.switchMode(value as "search" | "fetch")}
      ariaLabel="Playground view"
      idPrefix="playground"
      className="flex flex-1 flex-col space-y-8"
    >
      {/* Page heading */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[var(--border-subtle)]">
        <div>
          <h2 className="text-[var(--text-strong)]">Search Playground</h2>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Run queries and fetches across the provider fleet with live arbitration.
          </p>
        </div>
      </div>

      <PillTabsPanel value="search" className="flex flex-1 flex-col space-y-8">
        <SearchSection controller={controller} />
      </PillTabsPanel>

      <PillTabsPanel value="fetch" className="flex flex-1 flex-col space-y-8">
        <FetchSection controller={controller} />
      </PillTabsPanel>
    </PillTabs>
  )
}
