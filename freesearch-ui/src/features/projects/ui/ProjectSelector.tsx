import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { resolveLastProject, useProjectsOptional, writeLastProject } from "@/domains/projects"
import { ProjectSelectorMenu } from "./ProjectSelectorMenu"
import { ProjectSelectorTrigger } from "./ProjectSelectorTrigger"

export interface ProjectSelectorProps {
  collapsed: boolean
  onNavigate?: () => void
  /** Project of the current URL, or `null` on a global route. */
  currentProjectId: string | null
  /** Destination of one project choice; the shell keeps the current section. */
  pathForProject: (projectId: string) => string
}

/**
 * Project switcher of the sidebar.
 *
 * The control renders only once the projects surface has loaded; while it
 * loads or after a failure, the shell's main area shows the status or the
 * error with Retry. The menu lists projects by name. Choosing a project goes to the path
 * the shell builds (it keeps the current section) and remembers the choice as
 * the account's last project. Successful project page visits remember it too. Escape
 * and outside clicks dismiss the menu; Escape returns focus to the trigger.
 */
export function ProjectSelector({
  collapsed,
  onNavigate,
  currentProjectId,
  pathForProject,
}: ProjectSelectorProps) {
  const { accountId, availability, projects } = useProjectsOptional()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const navRef = useRef<HTMLElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (navRef.current !== null && !navRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("pointerdown", onPointerDown)
    return () => document.removeEventListener("pointerdown", onPointerDown)
  }, [open])

  if (availability !== "available") return null

  const current = projects.find((project) => project.id === currentProjectId) ?? null
  const lastId = resolveLastProject(accountId, projects)
  const shown = current ?? projects.find((project) => project.id === lastId) ?? null
  const label = shown?.name ?? "Select project"
  const accessibleName =
    shown !== null ? `Select project (current: ${shown.name})` : "Select project"

  const dismiss = () => {
    setOpen(false)
    triggerRef.current?.focus()
  }

  const choose = (projectId: string) => {
    writeLastProject(accountId, projectId)
    setOpen(false)
    onNavigate?.()
    navigate(pathForProject(projectId))
  }

  const goToList = () => {
    setOpen(false)
    onNavigate?.()
    navigate("/projects")
  }

  return (
    <nav
      ref={navRef}
      aria-label="Projects"
      className="relative shrink-0 px-2 pb-3"
    >
      <ProjectSelectorTrigger
        ref={triggerRef}
        collapsed={collapsed}
        open={open}
        label={label}
        accessibleName={accessibleName}
        hasProject={shown !== null}
        onToggle={() => setOpen((previous) => !previous)}
      />
      {open && (
        <ProjectSelectorMenu
          collapsed={collapsed}
          projects={[...projects].sort((a, b) => a.name.localeCompare(b.name))}
          currentId={currentProjectId}
          onChoose={choose}
          onList={goToList}
          onDismiss={dismiss}
        />
      )}
    </nav>
  )
}
