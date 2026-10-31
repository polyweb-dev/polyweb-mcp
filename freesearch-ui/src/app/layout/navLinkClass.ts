import { cn } from "cn"

/**
 * Shared class list of one sidebar navigation link.
 *
 * The Project group and the Primary group use the same row, active marker and
 * focus ring, so both groups read as one navigation system.
 */
export function navLinkClass(collapsed: boolean, isActive: boolean): string {
  return cn(
    "relative flex h-10 w-full items-center rounded-md text-[13px] font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] focus-visible:ring-inset motion-reduce:transition-none",
    collapsed ? "justify-center px-0" : "gap-3 px-3",
    isActive
      ? "bg-[var(--signal-muted)] text-[var(--text-strong)] before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-r before:bg-[var(--signal)]"
      : "text-[var(--muted)] hover:bg-[var(--secondary)] hover:text-[var(--text-strong)]"
  )
}
