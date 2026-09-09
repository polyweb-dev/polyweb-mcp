import type { FormEvent } from "react"
import { FileText } from "lucide-react"
import { ComposerShell } from "@/components/common/ComposerShell"
import { PillTabsList } from "@/components/common/PillTabs"
import { Button } from "@/components/ui/button"
import type { ProviderConfig } from "@/types/freesearch"
import { ProviderPicker } from "./ProviderPicker"

type FetchRequestFormOptions = {
  fetchUrl: string
  isSearching: boolean
  isFetching: boolean
  eligibleProviders: ProviderConfig[]
  selectedProviderId: string
  onSubmit: (event?: FormEvent) => void | Promise<void>
  onFetchUrlChange: (url: string) => void
  onProviderChange: (providerId: string) => void
}

export function FetchRequestForm({
  fetchUrl,
  isSearching,
  isFetching,
  eligibleProviders,
  selectedProviderId,
  onSubmit,
  onFetchUrlChange,
  onProviderChange,
}: FetchRequestFormOptions) {
  return (
    <form onSubmit={onSubmit} noValidate={false} className="w-full">
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
              onChange={(e) => onFetchUrlChange(e.target.value)}
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
            <ProviderPicker
              eligibleProviders={eligibleProviders}
              selectedProviderId={selectedProviderId}
              onProviderChange={onProviderChange}
            />

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
