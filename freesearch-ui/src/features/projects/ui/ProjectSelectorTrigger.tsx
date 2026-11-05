import { Boxes, ChevronDown } from "lucide-react"
import { cn } from "cn"
import type { Ref } from "react"

export interface ProjectSelectorTriggerProps {
  collapsed: boolean
  open: boolean
  label: string
  /** Accessible name: includes the current project when one is selected. */
  accessibleName: string
  onToggle: () => void
  ref?: Ref<HTMLButtonElement>
}

/** Trigger button of the project selector; icon-only on the collapsed rail. */
export function ProjectSelectorTrigger({
  collapsed,
  open,
  label,
  accessibleName,
  onToggle,
  ref,
}: ProjectSelectorTriggerProps) {
  return (
    <button
      type="button"
      ref={ref}
      aria-label={accessibleName}
      aria-haspopup="menu"
      aria-expanded={open}
      onClick={onToggle}
      title={label}
      className={cn(
        "flex min-h-10 w-full items-center rounded-md py-2 text-[13px] font-medium text-[var(--text)] transition-colors duration-150 hover:bg-[var(--secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] focus-visible:ring-inset motion-reduce:transition-none",
        collapsed ? "justify-center px-0" : "gap-2 px-3"
      )}
    >
      <Boxes aria-hidden="true" className="size-[18px] shrink-0" strokeWidth={1.8} />
      {!collapsed && (
        <>
          <span className="line-clamp-2 min-w-0 flex-1 break-words text-left">{label}</span>
          <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-[var(--muted)]" />
        </>
      )}
    </button>
  )
}
