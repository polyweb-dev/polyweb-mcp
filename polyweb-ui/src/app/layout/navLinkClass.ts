import { cn } from "cn"

/**
 * Shared class list of one sidebar navigation link.
 *
 * The Project group and the System group use the same 32px row, icon column
 * and active surface step, so both groups read as one navigation system.
 */
export function navLinkClass(collapsed: boolean, isActive: boolean): string {
  return cn(
    "relative flex h-8 w-full items-center rounded-md text-[13px] transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] focus-visible:ring-inset motion-reduce:transition-none",
    collapsed ? "justify-center px-0" : "gap-2.5 px-2.5",
    isActive
      ? "bg-[var(--raised)] font-medium text-[var(--text-strong)]"
      : "text-[var(--text)] hover:bg-[var(--raised)]/60 hover:text-[var(--text-strong)]"
  )
}

/** Icon class of one sidebar row: one size and stroke for every group. */
export const NAV_ICON_CLASS = "size-4 shrink-0"
