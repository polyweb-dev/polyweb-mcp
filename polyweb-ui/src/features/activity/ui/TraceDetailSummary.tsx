import type { ReactNode } from "react"
import { cn } from "cn"
import type { TraceActor, TraceDetail, TraceProviderAttempt } from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { traceActorLabel } from "@/shared/lib/identity"
import { formatLatency } from "@/shared/lib/formatTime"
import { IdentityLines } from "@/shared/ui/IdentityLines"
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
    <div key={label} className={cn("min-w-0 px-2.5 py-1.5 sm:px-3", divider(index))}>
      <dt className="text-[10px] leading-4 text-[var(--muted)]">{label}</dt>
      <dd className="min-w-0 text-[12px] leading-4 break-words text-[var(--text-strong)] tnum">{value}</dd>
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
 * Telemetry rail for the detail dialog: status, identity, attribution,
 * latency, and count share one responsive rail (two cells below `sm`, three
 * from `sm` up, five on wide dialogs) instead of floating as separate cards.
 * Scoped to one provider attempt, that attempt's own status, provider,
 * latency, and result count replace the trace totals and the scope is stated
 * beneath the rail.
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
    <div className="min-w-0 space-y-1">
      <dl className="grid min-w-0 grid-cols-2 overflow-hidden rounded-md border border-[var(--border-subtle)] bg-[var(--elevated)] divide-x divide-y divide-[var(--muted)] sm:grid-cols-3 sm:divide-y-0 lg:grid-cols-5 lg:divide-y-0">
        {cell("Status", <TraceStatusPill outcome={attempt?.outcome ?? trace.outcome} />, 0)}
        {cell("Provider", providerCell(trace, attempt), 1)}
        {cell("Initiated by", actorCell(trace.actor), 2)}
        {cell(
          attempt === null ? "Total latency" : "Provider latency",
          formatLatency(attempt === null ? trace.durationMs : attempt.durationMs),
          3
        )}
        {cell("Results", results === null ? "—" : String(results), 4)}
      </dl>
      {attempt !== null && (
        <p className="text-[12px] text-[var(--muted)]">
          Showing this provider's response; the timeline covers the whole trace
        </p>
      )}
    </div>
  )
}

/**
 * Initiated-by cell: the human display name (full name, then username, then
 * email with disambiguation) when known; API-key rows stay key-identified;
 * legacy/unknown rows stay quiet. The two-line rail entry truncates each line
 * with the full contact title, so mid-word email breaks never appear.
 */
function actorCell(actor: TraceActor): ReactNode {
  if (actor.kind === "project_api_key") return "API key"
  const label = traceActorLabel(actor)
  if (label === null) return "—"
  if (actor.displayName === null) {
    return (
      <span className="block truncate" title={label}>
        {label}
      </span>
    )
  }
  return <IdentityLines primary={actor.displayName} secondary={actor.email} detail={label} />
}
