import { ChevronsUpDown, FolderOpen } from "lucide-react"
import { cn } from "cn"
import type { Ref } from "react"

export interface ProjectSelectorTriggerProps {
  collapsed: boolean
  open: boolean
  label: string
  /** Accessible name: includes the current project when one is selected. */
  accessibleName: string
  /** `false` while no project is open or remembered. */
  hasProject: boolean
  onToggle: () => void
  ref?: Ref<HTMLButtonElement>
}

/** First letter of a project name for the switcher mark. */
function projectInitial(name: string): string {
  return name.trim().slice(0, 1).toUpperCase() || "?"
}

/**
 * Trigger of the project switcher: a lettered mark and the full project
 * name, wrapping to two lines before it truncates. Icon-only on the
 * collapsed rail.
 */
export function ProjectSelectorTrigger({
  collapsed,
  open,
  label,
  accessibleName,
  hasProject,
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
        "flex min-h-10 w-full items-center rounded-md border border-[var(--border-subtle)] bg-[var(--surface)] py-1.5 text-left transition-colors duration-150 hover:bg-[var(--raised)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] aria-expanded:bg-[var(--raised)] motion-reduce:transition-none",
        collapsed ? "justify-center px-0" : "gap-2.5 pr-2 pl-1.5"
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "grid size-6 shrink-0 place-items-center rounded-[5px] text-[12px] font-semibold",
          hasProject ? "bg-[var(--signal)] text-white" : "bg-[var(--raised)] text-[var(--muted)]"
        )}
      >
        {hasProject ? projectInitial(label) : <FolderOpen className="size-3.5" strokeWidth={1.75} />}
      </span>
      {!collapsed && (
        <>
          <span
            className={cn(
              "line-clamp-2 min-w-0 flex-1 break-words text-[13px] leading-[18px] font-medium",
              hasProject ? "text-[var(--text-strong)]" : "text-[var(--muted)]"
            )}
          >
            {label}
          </span>
          <ChevronsUpDown aria-hidden="true" className="size-3.5 shrink-0 text-[var(--muted)]" />
        </>
      )}
    </button>
  )
}
