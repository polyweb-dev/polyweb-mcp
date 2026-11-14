import type { ReactNode } from "react"

export interface IdentityLinesProps {
  /** Visible primary line: the display name or the key name. */
  primary: string
  /** Visible muted second line when it differs from the primary. */
  secondary?: string | null
  /** Monospace token appended to the second line (for example a key prefix). */
  secondaryMono?: string | null
  /** Full title of the primary line; defaults to the primary with its second line. */
  detail?: string | null
}

function present(value: string | null | undefined): value is string {
  return value !== undefined && value !== null && value !== ""
}

/**
 * Two-line identity for tables and the detail rail.
 *
 * Business-agnostic: plain strings only, so it never decides what may be
 * shown (callers must not pass an email outside the allowed views). The
 * primary truncates with the full text as its title; the second line shows
 * muted when present and differs, so rows stay distinguishable where an
 * action overlay covers hover titles.
 */
export function IdentityLines({ primary, secondary, secondaryMono, detail }: IdentityLinesProps): ReactNode {
  const lead = present(secondary) && secondary !== primary ? secondary : null
  const mono = present(secondaryMono) ? secondaryMono : null
  const contact = [lead, mono].filter(present).join(" ")
  const title = detail ?? (contact !== "" ? `${primary} (${contact})` : primary)
  return (
    <span className="flex min-w-0 max-w-[200px] flex-col leading-4">
      <span className="truncate" title={title}>
        {primary}
      </span>
      {contact !== "" && (
        <span className="truncate text-[11px] text-[var(--muted)]" title={contact}>
          {lead}
          {lead !== null && mono !== null && " "}
          {mono !== null && <span className="font-mono">{mono}</span>}
        </span>
      )}
    </span>
  )
}
