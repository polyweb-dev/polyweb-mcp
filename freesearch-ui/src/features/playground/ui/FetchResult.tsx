import type { FetchResponse } from "@/domains/execution"
import { providerIdentity } from "@/domains/providers"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"

export interface FetchResultProps {
  result: FetchResponse
  copied: boolean
  onCopy: (markdown: string) => void
}

/** Fetch result: metadata column plus the parsed markdown document. */
export function FetchResult({ result: activeFetch, copied, onCopy }: FetchResultProps) {
  // The wire name holds the raw provider value ("you"). The catalog name is the
  // display name, and `providerIdentity` resolves the alias plus the logo key.
  const provider = providerIdentity(activeFetch.document.providerId)
  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start pt-2">
      {/* Left Column: Metadata & Outline */}
      <div className="lg:col-span-4 p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-4">
        <div>
          <span className="text-[12px] text-[var(--signal)] block mb-1">
            Document Metadata
          </span>
          <h3 className="text-[16px] font-medium text-[var(--text-strong)] leading-snug">
            {activeFetch.document.title}
          </h3>
        </div>

        <div className="space-y-2.5 text-[13px] text-[var(--muted)]">
          <div>
            <span className="text-[12px] block mb-1">Source URL</span>
            <div className="p-2 rounded bg-[var(--surface)] border border-[var(--border-subtle)] font-mono text-[12px] text-[var(--text)] break-all">
              {activeFetch.document.url}
            </div>
          </div>

          <div className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)]">
            <span>Provider</span>
            <ProviderBadge
              providerId={provider.id}
              name={provider.name}
              className="text-[var(--text)]"
              logoClassName="size-3.5"
            />
          </div>

          <div className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)]">
            <span>Status code</span>
            <span className="tnum" style={{ color: "var(--status-healthy)" }} title="HTTP status not exposed by backend">
              {activeFetch.document.statusCode ?? "—"}
            </span>
          </div>

          <div className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)]">
            <span>Content length</span>
            <span className="text-[var(--text)] tnum">
              {new TextEncoder().encode(activeFetch.document.content).length} bytes
            </span>
          </div>

          <div className="flex items-center justify-between py-1.5">
            <span>Execution time</span>
            <span className="text-[var(--text)] tnum">{activeFetch.executionTimeMs}ms</span>
          </div>
        </div>
      </div>

      {/* Right Column: Markdown Document Content */}
      <div className="lg:col-span-8 p-5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-3">
        <div className="flex items-center justify-between pb-3 border-b border-[var(--border-subtle)]">
          <span className="text-[13px] font-medium text-[var(--text-strong)]">Parsed Markdown Document</span>
          <button
            type="button"
            onClick={() => onCopy(activeFetch.document.markdown)}
            className="text-[13px] px-3 py-1 rounded bg-[var(--surface)] border border-[var(--border-subtle)] text-[var(--signal)] hover:text-white transition-colors"
          >
            {copied ? "Copied" : "Copy markdown"}
          </button>
        </div>

        <pre className="p-4 rounded-md bg-[var(--surface)] border border-[var(--border-subtle)] text-[13px] text-[var(--text)] whitespace-pre-wrap leading-relaxed max-h-[600px] overflow-auto">
          {activeFetch.document.markdown}
        </pre>
      </div>
    </div>
  )
}
