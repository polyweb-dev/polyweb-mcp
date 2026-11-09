import { PillTabs } from "@/shared/ui/PillTabs"
import { PillTabsPanel } from "@/shared/ui/PillTabsPanel"
import { usePlaygroundController } from "../model/usePlaygroundController"
import type { PlaygroundScope } from "../model/usePlaygroundController"
import { PageHeader } from "@/shared/ui/PageHeader"
import { FetchSection } from "./FetchSection"
import { SearchSection } from "./SearchSection"

/**
 * Search playground page: Search/Fetch pill views over one controller. A mode
 * the caller lacks permission for stays visible but disabled.
 */
export function PlaygroundPage({ scope }: { scope: PlaygroundScope }) {
  const controller = usePlaygroundController(scope)
  const viewOptions = [
    { value: "search", label: "Search", disabled: !controller.canSearch },
    { value: "fetch", label: "Fetch", disabled: !controller.canFetch },
  ]
  return (
    <PillTabs
      options={viewOptions}
      value={controller.mode}
      onValueChange={(value) => controller.switchMode(value as "search" | "fetch")}
      ariaLabel="Playground view"
      idPrefix="playground"
      className="flex flex-1 flex-col space-y-6"
    >
      {/* Page heading */}
      <PageHeader
        title="Playground"
        description="Run search and fetch through this project's providers"
      />

      <PillTabsPanel value="search" className="flex flex-1 flex-col space-y-8">
        <SearchSection controller={controller} />
      </PillTabsPanel>

      <PillTabsPanel value="fetch" className="flex flex-1 flex-col space-y-8">
        <FetchSection controller={controller} />
      </PillTabsPanel>
    </PillTabs>
  )
}
