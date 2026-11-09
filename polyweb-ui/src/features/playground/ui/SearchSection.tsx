import type { PlaygroundController } from "../model/usePlaygroundController"
import { isNoProviderConfigured } from "./noProviderConfigured"
import { ProviderSetupNotice } from "./ProviderSetupNotice"
import { SearchComposer } from "./SearchComposer"
import { SearchResults } from "./SearchResults"

/** Search panel: fixed composer position, error banner, results. */
export function SearchSection({ controller }: { controller: PlaygroundController }) {
  return (
    <>
      <div
        data-testid="search-layout"
        data-state="docked"
        className="top-docked w-full"
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
