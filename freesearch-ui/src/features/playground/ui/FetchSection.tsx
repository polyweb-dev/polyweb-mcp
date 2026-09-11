import type { PlaygroundController } from "../model/usePlaygroundController"
import { FetchComposer } from "./FetchComposer"
import { FetchResult } from "./FetchResult"

/** Fetch panel: hero/docked composer wrapper, error banner, document. */
export function FetchSection({ controller }: { controller: PlaygroundController }) {
  return (
    <>
      <div
        data-testid="fetch-layout"
        data-state={controller.hasFetchContent ? "docked" : "hero"}
        className={"transition-all duration-300 ease-out motion-reduce:transition-none " + (controller.hasFetchContent
          ? "top-docked"
          : "w-full mx-auto flex flex-1 min-h-[55vh] max-w-3xl flex-col justify-center")}
      >
        <FetchComposer controller={controller} />
      </div>
      {controller.fetchError && (
        <p className="text-[13px]" style={{ color: "var(--status-danger)" }}>
          {controller.fetchError}
        </p>
      )}

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
