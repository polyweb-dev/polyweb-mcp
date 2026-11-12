import type { ReactNode } from "react"

export interface IdentityLinesProps {
  /** Visible primary line: the display name, else the email, else the fallback. */
  primary: string
  /** Visible contact line: the email when it names someone the primary hides. */
  secondary?: string | null
  /** Full contact title: the existing `Display (email)` detail helper output. */
  detail?: string | null
}

/**
 * Two-line contact identity for tables and the detail rail.
 *
 * Business-agnostic: primary and contact strings only. The primary truncates
 * with the full contact as its title; the contact shows as a visible muted
 * second line when it differs, so rows stay disambiguated where an action
 * overlay covers hover titles. Truncation keeps long contacts on their own
 * lines without mid-word breaks.
 */
export function IdentityLines({ primary, secondary, detail }: IdentityLinesProps): ReactNode {
  const contact =
    secondary !== undefined && secondary !== null && secondary !== "" && secondary !== primary
      ? secondary
      : null
  const title = detail ?? (contact !== null ? `${primary} (${contact})` : primary)
  return (
    <span className="flex min-w-0 max-w-[200px] flex-col leading-4">
      <span className="truncate" title={title}>
        {primary}
      </span>
      {contact !== null && (
        <span className="truncate text-[11px] text-[var(--muted)]" title={contact}>
          {contact}
        </span>
      )}
    </span>
  )
}
