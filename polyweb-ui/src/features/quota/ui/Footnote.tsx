import type { ReactNode } from "react"

export interface FootnoteProps {
  children: ReactNode
  /** Extra layout of the host block, such as a separator above the note. */
  className?: string
}

const FOOTNOTE = "text-[11px] leading-relaxed text-[var(--muted)]"

/**
 * One subtle footnote.
 *
 * A title note, a card note, and a section closing note share this one quiet
 * style, so a note never competes with the data of its block.
 */
export function Footnote({ children, className }: FootnoteProps): ReactNode {
  return <p className={className === undefined ? FOOTNOTE : FOOTNOTE + " " + className}>{children}</p>
}
