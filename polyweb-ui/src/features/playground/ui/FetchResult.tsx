import type { ReactNode } from "react"
import type { FetchResponse } from "@/domains/execution"
import { providerIdentity } from "@/domains/providers"
import { formatLatency } from "@/shared/lib/formatTime"
import { Button } from "@/shared/ui/button"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { documentSizeText } from "../model/documentSize"

export interface FetchResultProps {
  result: FetchResponse
  copied: boolean
  onCopy: (markdown: string) => void
}

/** One label/value row of the document facts. */
function factRow(label: string, value: ReactNode, last = false): ReactNode {
  return (
    <div
      className={`flex items-center justify-between py-1.5 ${last ? "" : "border-b border-[var(--border-subtle)]"}`}
    >
      <span>{label}</span>
      {value}
    </div>
  )
}

/** Fetch result: document facts beside the parsed markdown document. */
export function FetchResult({ result: activeFetch, copied, onCopy }: FetchResultProps) {
  // The wire name holds the raw provider value ("you"). The catalog name is the
  // display name, and `providerIdentity` resolves the alias plus the logo key.
  const provider = providerIdentity(activeFetch.document.providerId)
  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start pt-2">
      <div className="lg:col-span-4 p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-4">
        <div>
          <span className="mb-1 block text-[12px] text-[var(--muted)]">Document metadata</span>
          <h3 className="text-[16px] font-medium text-[var(--text-strong)] leading-snug">
            {activeFetch.document.title}
          </h3>
        </div>

        <div className="space-y-2.5 text-[13px] text-[var(--muted)]">
          <div>
            <span className="text-[12px] block mb-1">Source URL</span>
            <a
              href={activeFetch.document.url}
              target="_blank"
              rel="noreferrer"
              className="fs-link mono block text-[12px] break-all"
            >
              {activeFetch.document.url}
            </a>
          </div>

          {factRow(
            "Provider",
            <ProviderBadge
              providerId={provider.id}
              name={provider.name}
              className="text-[var(--text)]"
              logoClassName="size-3.5"
            />
          )}
          {factRow(
            "Content length",
            <span className="text-[var(--text)] tnum">
              {documentSizeText(new TextEncoder().encode(activeFetch.document.content).length)}
            </span>
          )}
          {factRow(
            "Latency",
            <span className="text-[var(--text)] tnum">{formatLatency(activeFetch.executionTimeMs)}</span>,
            true
          )}
        </div>
      </div>

      <div className="lg:col-span-8 p-5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-3">
        <div className="flex items-center justify-between pb-3 border-b border-[var(--border-subtle)]">
          <span className="text-[13px] font-medium text-[var(--text-strong)]">Parsed markdown</span>
          <Button
            type="button"
            variant="outline"
            size="form"
            onClick={() => onCopy(activeFetch.document.markdown)}
          >
            {copied ? "Copied" : "Copy markdown"}
          </Button>
        </div>

        <pre className="p-4 rounded-md bg-[var(--surface)] border border-[var(--border-subtle)] text-[13px] text-[var(--text)] whitespace-pre-wrap leading-relaxed max-h-[600px] overflow-auto">
          {activeFetch.document.markdown}
        </pre>
      </div>
    </div>
  )
}
