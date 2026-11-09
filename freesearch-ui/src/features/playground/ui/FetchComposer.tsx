import { FileText } from "lucide-react"
import { Button } from "@/shared/ui/button"
import { ComposerShell } from "@/shared/ui/ComposerShell"
import { ProviderSelect } from "@/shared/ui/ProviderSelect"
import type { PlaygroundController } from "../model/usePlaygroundController"
import { PlaygroundModeTabs } from "./PlaygroundModeTabs"

/** The provider field style of the composer footer. */
const providerFieldClass =
  "min-w-48 rounded border border-[var(--border-subtle)] bg-[var(--elevated)] px-2.5 py-1 text-[13px] text-[var(--text)] outline-none"

/**
 * Fetch request form via the shared composer shell. Mounted once per Fetch
 * panel mount to preserve form/input nodes, value, and focus while loading.
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
          <div className="flex min-w-0 items-center gap-3">
            <PlaygroundModeTabs />
            <div className="relative min-w-0 flex-1">
              <div
                className="absolute left-0 top-1/2 -translate-y-1/2 pl-1"
                style={{ color: "var(--muted)" }}
              >
                <FileText aria-hidden="true" className="size-4" />
              </div>
              <input
                type="url"
                value={fetchUrl}
                onChange={(e) => setFetchUrl(e.target.value)}
                placeholder="URL to fetch"
                aria-label="URL to fetch"
                className="w-full rounded-md bg-transparent py-3 pl-8 pr-32 text-[15px] font-mono outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--signal)]/40 placeholder:font-sans placeholder:text-[var(--muted)]"
                style={{ color: "var(--text-strong)" }}
              />
              <div className="absolute right-0 top-1/2 -translate-y-1/2">
                <Button
                  type="submit"
                  disabled={isSearching || isFetching || controller.noProviderForMode}
                  className="inline-flex items-center gap-2 rounded-md px-5 py-2 text-[13px] font-medium text-white"
                  style={{ background: "var(--signal)" }}
                >
                  <FileText aria-hidden="true" className="size-3.5" />
                  {isSearching || isFetching ? "Executing..." : "Fetch"}
                </Button>
              </div>
            </div>
          </div>
        }
        footer={
          <div className="flex flex-wrap items-center gap-6">
            {controller.providersError && (
              <span role="alert" className="flex items-center gap-2 text-[var(--status-danger)]">
                Couldn't load this project's providers.
                <Button
                  type="button"
                  variant="outline"
                  size="form"
                  onClick={() => controller.retryProviders()}
                >
                  Retry
                </Button>
              </span>
            )}
            <div className="flex items-center gap-2">
              <label htmlFor="playground-fetch-provider">Provider</label>
              <ProviderSelect
                id="playground-fetch-provider"
                testId="playground-fetch-provider"
                className={providerFieldClass}
                value={selectedProviderId}
                options={[
                  { value: "auto", label: "Auto" },
                  ...eligibleProviders.map((provider) => ({
                    value: provider.id,
                    label: provider.name,
                  })),
                ]}
                onValueChange={setSelectedProviderId}
              />
            </div>
          </div>
        }
      />
    </form>
  )
}
