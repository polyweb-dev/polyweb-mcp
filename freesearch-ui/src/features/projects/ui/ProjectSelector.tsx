import { useEffect, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router"
import { useProjectsOptional, writeLastProject } from "@/domains/projects"
import { ProjectSelectorMenu } from "./ProjectSelectorMenu"
import { ProjectSelectorTrigger } from "./ProjectSelectorTrigger"

/** `/p/<id>` or `/p/<id>/members` — the project section of the current URL. */
const PROJECT_URL_RE = /^\/p\/([^/]+?)(\/members)?$/

export interface ProjectSelectorProps {
  collapsed: boolean
  onNavigate?: () => void
}

/**
 * Project switcher of the sidebar.
 *
 * The control renders only while the projects surface is available; an
 * unavailable rollout hides it entirely. Choosing a project keeps the current
 * section (`members` stays on members) and remembers the choice as the
 * account's last project. Escape and outside clicks dismiss the menu; Escape
 * returns focus to the trigger.
 */
export function ProjectSelector({ collapsed, onNavigate }: ProjectSelectorProps) {
  const { accountId, availability, rolloutState, projects } = useProjectsOptional()
  const { pathname } = useLocation()
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

  const match = PROJECT_URL_RE.exec(pathname)
  const currentId = match?.[1] ?? null
  const section = match?.[2] === "/members" ? "members" : null
  const current = projects.find((project) => project.id === currentId) ?? null
  const label = current?.name ?? "Select project"
  const accessibleName =
    current !== null ? `Select project (current: ${current.name})` : "Select project"

  const dismiss = () => {
    setOpen(false)
    triggerRef.current?.focus()
  }

  const choose = (projectId: string) => {
    writeLastProject(accountId, projectId)
    setOpen(false)
    onNavigate?.()
    navigate(section === "members" ? `/p/${projectId}/members` : `/p/${projectId}`)
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
      className="relative shrink-0 border-b border-[var(--border-subtle)] px-2 py-3"
    >
      <ProjectSelectorTrigger
        ref={triggerRef}
        collapsed={collapsed}
        open={open}
        label={label}
        accessibleName={accessibleName}
        showPreviewBadge={rolloutState === "preview"}
        onToggle={() => setOpen((previous) => !previous)}
      />
      {open && (
        <ProjectSelectorMenu
          collapsed={collapsed}
          projects={projects}
          currentId={currentId}
          onChoose={choose}
          onList={goToList}
          onDismiss={dismiss}
        />
      )}
    </nav>
  )
}
