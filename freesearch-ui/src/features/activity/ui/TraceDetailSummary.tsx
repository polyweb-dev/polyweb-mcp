import type { ReactNode } from "react"
import { cn } from "cn"
import type { TraceDetail, TraceProviderAttempt } from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { TraceStatusPill } from "./TraceStatusPill"

const AGGREGATED_PROVIDER = "aggregated"

/**
 * Internal dividers: the rail reads as one strip, not four floating cards.
 * Two columns below `sm` (each row closed by a divider, none left orphaned),
 * four columns from `sm` up; every cell is the same height and shares the
 * dialog's single inset.
 */
function divider(index: number): string {
  return cn(
    index % 2 === 1 && "border-l",
    index < 2 && "border-b sm:border-b-0",
    index > 0 && "sm:border-l",
    "border-[var(--border-subtle)]"
  )
}

function cell(label: string, value: ReactNode, index: number): ReactNode {
  return (
    <div key={label} className={cn("min-w-0 px-4 py-3", divider(index))}>
      <dt className="block text-[12px] text-[var(--muted)]">{label}</dt>
      <dd className="mt-0.5 block min-w-0 text-[13px] text-[var(--text-strong)] tnum">{value}</dd>
    </div>
  )
}

/**
 * The recorded provider identity: a logo and name for a known provider, the
 * plain group label for a fanout, and the recorded text when nothing was named.
 */
function providerCell(trace: TraceDetail, attempt: TraceProviderAttempt | null): ReactNode {
  const providerId = attempt === null ? trace.provider : attempt.providerId
  const label = attempt === null ? trace.providerLabel : attempt.providerLabel
  if (providerId === null || providerId === "") {
    return (
      <>
        {label}
        {attempt !== null && (
          <span className="ml-1.5 text-[11px] text-[var(--muted)]">Name not recorded</span>
        )}
      </>
    )
  }
  const identity = providerIdentity(providerId)
  // The fanout group keeps its recorded label; it has no vendor identity.
  if (identity.id === "" || identity.id === AGGREGATED_PROVIDER) return <span>{label}</span>
  return <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-3.5" />
}

/**
 * Telemetry rail for the detail dialog: one definition list with four
 * equal-height cells, so status, identity, latency, and count line up on one
 * baseline instead of floating as separate cards. Scoped to one provider
 * attempt, that attempt's own status, provider, latency, and result count
 * replace the trace totals and the scope is stated beneath the rail.
 */
export function TraceDetailSummary({
  trace,
  attempt,
}: {
  trace: TraceDetail
  attempt: TraceProviderAttempt | null
}) {
  const results = attempt === null ? trace.resultCount : attempt.resultCount
  return (
    <div className="min-w-0 space-y-2">
      <dl className="grid min-w-0 grid-cols-2 overflow-hidden rounded-md border border-[var(--border-subtle)] bg-[var(--elevated)] sm:grid-cols-4">
        {cell("Status", <TraceStatusPill outcome={attempt?.outcome ?? trace.outcome} />, 0)}
        {cell("Provider", providerCell(trace, attempt), 1)}
        {cell(
          attempt === null ? "Total latency" : "Provider latency",
          `${attempt === null ? trace.durationMs : attempt.durationMs}ms`,
          2
        )}
        {cell("Results", results === null ? "—" : String(results), 3)}
      </dl>
      {attempt !== null && (
        <p className="text-[12px] text-[var(--muted)]">
          Showing this provider's response. The trajectory view below still covers the whole
          trace.
        </p>
      )}
    </div>
  )
}
