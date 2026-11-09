import { useEffect, useRef } from "react"
import type { KeyboardEvent } from "react"
import { Check, LayoutList } from "lucide-react"
import { cn } from "cn"
import type { Project } from "@/domains/projects"
import { MENU_ITEM_CLASS, MENU_SEPARATOR_CLASS } from "@/shared/ui/menuStyles"
import { Tag } from "@/shared/ui/Tag"

export interface ProjectSelectorMenuProps {
  collapsed: boolean
  /** Projects in display order (the selector sorts them by name). */
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
 * Rows share the menu row style of every popup; a long name truncates and
 * shows in full on hover. The first item takes focus on open; Arrow keys move
 * between items and Escape dismisses back to the trigger.
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
        "absolute z-50 mt-1 max-h-[60vh] overflow-y-auto rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] p-1 shadow-lg",
        collapsed ? "top-0 left-14 w-64" : "right-2 left-2"
      )}
    >
      {projects.map((project) => {
        const current = project.id === currentId
        return (
          <button
            key={project.id}
            type="button"
            role="menuitem"
            title={project.name}
            aria-current={current ? "true" : undefined}
            onClick={() => onChoose(project.id)}
            className={MENU_ITEM_CLASS}
          >
            <span className="min-w-0 flex-1 truncate">{project.name}</span>
            {project.status === "archived" && <Tag>Archived</Tag>}
            {current && <Check aria-hidden="true" className="text-[var(--text-strong)]" />}
          </button>
        )
      })}
      <div aria-hidden="true" className={MENU_SEPARATOR_CLASS} />
      <button type="button" role="menuitem" onClick={onList} className={MENU_ITEM_CLASS}>
        <LayoutList aria-hidden="true" className="text-[var(--muted)]" />
        All projects
      </button>
    </div>
  )
}
