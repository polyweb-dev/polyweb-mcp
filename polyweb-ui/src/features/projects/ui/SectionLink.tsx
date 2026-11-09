import type { ReactNode } from "react"
import { ChevronRight } from "lucide-react"
import { Link } from "react-router"

/** Quiet section action of the overview: secondary text with a chevron, no accent. */
export function SectionLink({ to, children, "aria-label": ariaLabel }: { to: string; children: ReactNode; "aria-label"?: string }) {
  return (
    <Link
      to={to}
      aria-label={ariaLabel}
      className="inline-flex items-center gap-1 text-[13px] text-[var(--muted)] transition-colors hover:text-[var(--text-strong)] focus-visible:text-[var(--text-strong)] focus-visible:underline focus-visible:outline-none"
    >
      {children}
      <ChevronRight aria-hidden="true" className="size-3.5" />
    </Link>
  )
}
