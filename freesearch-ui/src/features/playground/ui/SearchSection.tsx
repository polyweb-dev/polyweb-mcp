import type { PlaygroundController } from "../model/usePlaygroundController"
import { isNoProviderConfigured } from "./noProviderConfigured"
import { ProviderSetupNotice } from "./ProviderSetupNotice"
import { SearchComposer } from "./SearchComposer"
import { SearchResults } from "./SearchResults"

/** Search panel: hero/docked composer wrapper, error banner, results. */
export function SearchSection({ controller }: { controller: PlaygroundController }) {
  return (
    <>
      <div
        data-testid="search-layout"
        data-state={controller.hasSearchContent ? "docked" : "hero"}
        className={"transition-all duration-300 ease-out motion-reduce:transition-none " + (controller.hasSearchContent
          ? "top-docked"
          : "w-full mx-auto flex flex-1 min-h-[55vh] max-w-3xl flex-col justify-center")}
      >
        <SearchComposer controller={controller} />
      </div>

      {controller.noProviderForMode && <ProviderSetupNotice projectId={controller.projectId} />}

      {controller.searchError !== null &&
        (isNoProviderConfigured(controller.searchError) ? (
          <ProviderSetupNotice projectId={controller.projectId} />
        ) : (
          <p className="text-[13px]" style={{ color: "var(--status-danger)" }}>
            {controller.searchError}
          </p>
        ))}

      {/* Widescreen Results Layout: Results List + Inspector Pane */}
      {controller.activeSearch && (
        <SearchResults controller={controller} result={controller.activeSearch} />
      )}
    </>
  )
}
