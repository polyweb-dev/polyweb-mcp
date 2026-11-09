import type { PlaygroundController } from "../model/usePlaygroundController"
import { FetchComposer } from "./FetchComposer"
import { FetchErrorBanner } from "./FetchErrorBanner"
import { FetchResult } from "./FetchResult"
import { isNoProviderConfigured } from "./noProviderConfigured"
import { ProviderSetupNotice } from "./ProviderSetupNotice"

/** Fetch panel: fixed composer position, error banner, document. */
export function FetchSection({ controller }: { controller: PlaygroundController }) {
  return (
    <>
      <div
        data-testid="fetch-layout"
        data-state="docked"
        className="top-docked w-full"
      >
        <FetchComposer controller={controller} />
      </div>
      {controller.noProviderForMode && <ProviderSetupNotice projectId={controller.projectId} />}

      {controller.fetchError !== null &&
        (isNoProviderConfigured(controller.fetchError) ? (
          <ProviderSetupNotice projectId={controller.projectId} />
        ) : (
          <FetchErrorBanner error={controller.fetchError} />
        ))}

      {/* Fetch result — Widescreen 2-column layout */}
      {controller.activeFetch && (
        <FetchResult
          result={controller.activeFetch}
          copied={controller.copied}
          onCopy={controller.copyToClipboard}
        />
      )}
    </>
  )
}
