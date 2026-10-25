import { useEffect, useRef } from "react"
import type { KeyboardEvent } from "react"
import { cn } from "cn"
import type { Project } from "@/domains/projects"

const MENU_ITEM =
  "flex w-full cursor-default items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-[13px] text-[var(--text)] hover:bg-[var(--surface)] focus-visible:outline-none focus-visible:bg-[var(--surface)]"

export interface ProjectSelectorMenuProps {
  collapsed: boolean
  projects: Project[]
  currentId: string | null
  onChoose: (projectId: string) => void
  onList: () => void
  /** Close the menu and return focus to the trigger. */
  onDismiss: () => void
}

/**
 * Open menu of the project selector.
 *
 * The first item takes focus on open; Arrow keys move between items and
 * Escape dismisses back to the trigger, so the popup behaves like a menu.
 */
export function ProjectSelectorMenu({
  collapsed,
  projects,
  currentId,
  onChoose,
  onList,
  onDismiss,
}: ProjectSelectorMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
  }, [])

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault()
      event.stopPropagation()
      onDismiss()
      return
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return
    event.preventDefault()
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []
    )
    if (items.length === 0) return
    const index = items.indexOf(document.activeElement as HTMLElement)
    const step = event.key === "ArrowDown" ? 1 : -1
    items[(index + step + items.length) % items.length]?.focus()
  }

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label="Projects"
      onKeyDown={onKeyDown}
      className={cn(
        "absolute z-50 mt-1 max-h-[60vh] w-56 overflow-y-auto rounded border border-[var(--border-subtle)] bg-[var(--elevated)] p-1 shadow-lg",
        collapsed ? "left-14 top-0" : "left-2 right-2"
      )}
    >
      {projects.map((project) => (
        <button
          key={project.id}
          type="button"
          role="menuitem"
          aria-current={project.id === currentId ? "true" : undefined}
          onClick={() => onChoose(project.id)}
          className={MENU_ITEM}
        >
          <span className="min-w-0 truncate">{project.name}</span>
          {project.status === "archived" && (
            <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">
              Archived
            </span>
          )}
        </button>
      ))}
      <button type="button" role="menuitem" onClick={onList} className={MENU_ITEM}>
        All projects
      </button>
    </div>
  )
}
