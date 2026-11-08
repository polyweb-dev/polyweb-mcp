import { Menu, PanelLeftClose, X } from "lucide-react"
import { useLocation } from "react-router"
import { cn } from "cn"
import { useAuth } from "@/domains/auth"
import { ProjectSelector } from "@/features/projects/ui/ProjectSelector"
import { Button } from "@/shared/ui/button"
import { parseProjectPath, projectIdFromPath, projectPath } from "../routes"
import { Brand } from "./SidebarBrand"
import { NavList } from "./SidebarNavList"
import { ProjectNav } from "./SidebarProjectNav"
import { SidebarAccountMenu } from "./SidebarAccountMenu"
import { useSidebarState } from "./useSidebarState"

export interface SidebarProps {
  collapsed?: boolean
  defaultCollapsed?: boolean
  onCollapsedChange?: (collapsed: boolean) => void
}

/** Collapse control label of one sidebar mode. */
function collapseLabel(isCollapsed: boolean): string {
  return isCollapsed ? "Expand sidebar" : "Collapse sidebar"
}

/**
 * One reset key for the ephemeral account popup. A route, account, or sidebar
 * mode change gives a new key, so no stale identity or action stays open.
 */
function accountMenuKey(
  pathname: string,
  accountId: string | undefined,
  isCollapsed: boolean
): string {
  const mode = isCollapsed ? "collapsed" : "expanded"
  return `${pathname}|${accountId ?? "anonymous"}|${mode}`
}

/**
 * Project selection of the current URL: the open project and a path builder
 * that keeps the current section on a project switch.
 */
function projectSelection(pathname: string) {
  const section = parseProjectPath(pathname)?.section ?? "overview"
  return {
    currentProjectId: projectIdFromPath(pathname),
    pathForProject: (projectId: string) => projectPath(projectId, section),
  }
}

/**
 * Brand row of the desktop rail.
 *
 * The collapsed rail shows the logo as the expansion control itself, so the
 * rail keeps one button and a stable hit area. The expanded rail keeps the
 * static brand and its adjacent collapse control.
 */
function renderBrandRow(isCollapsed: boolean, onToggle: () => void) {
  if (isCollapsed) return <Brand collapsed onExpand={onToggle} />

  return (
    <div className="flex h-14 shrink-0 items-center justify-between pr-2">
      <Brand />
      <Button
        variant="ghost"
        size="icon-lg"
        aria-label={collapseLabel(isCollapsed)}
        aria-expanded={!isCollapsed}
        aria-controls="primary-sidebar"
        onClick={onToggle}
        className="text-[var(--muted)]"
      >
        <PanelLeftClose aria-hidden="true" strokeWidth={1.75} />
      </Button>
    </div>
  )
}

/** Overlay drawer of the compact layout, with the account row at its foot. */
function renderDrawer(
  menuKey: string,
  drawerOpen: boolean,
  onClose: (returnFocus?: boolean) => void,
  pathname: string
) {
  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <button
        type="button"
        aria-label="Dismiss navigation overlay"
        data-testid="sidebar-scrim"
        onClick={() => onClose(true)}
        className="absolute inset-0 bg-[var(--surface)]/80"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        className="relative flex h-full w-72 flex-col border-r border-[var(--border-subtle)] bg-[var(--elevated)] motion-reduce:transition-none"
      >
        <div className="flex items-center justify-between pr-3">
          <Brand />
          <Button
            variant="ghost"
            size="icon-lg"
            aria-label="Close navigation"
            onClick={() => onClose(true)}
            className="text-[var(--muted)]"
          >
            <X aria-hidden="true" />
          </Button>
        </div>
        <ProjectSelector
          collapsed={false}
          onNavigate={() => onClose()}
          {...projectSelection(pathname)}
        />
        <ProjectNav collapsed={false} onNavigate={() => onClose()} />
        <NavList collapsed={false} onNavigate={() => onClose()} />
        <div className="shrink-0 p-2">
          <SidebarAccountMenu key={`drawer|${drawerOpen}|${menuKey}`} collapsed={false} />
        </div>
      </div>
    </div>
  )
}

export function Sidebar({
  collapsed,
  defaultCollapsed = false,
  onCollapsedChange,
}: SidebarProps) {
  const { pathname } = useLocation()
  const { account } = useAuth()
  const {
    isCollapsed,
    drawerOpen,
    openerRef,
    openDrawer,
    closeDrawer,
    toggleCollapsed,
  } = useSidebarState({
    ...(collapsed !== undefined ? { collapsed } : {}),
    defaultCollapsed,
    ...(onCollapsedChange !== undefined ? { onCollapsedChange } : {}),
  })

  const menuKey = accountMenuKey(pathname, account?.id, isCollapsed)

  return (
    <>
      <button
        ref={openerRef}
        type="button"
        aria-label="Open navigation"
        onClick={openDrawer}
        className="fixed left-3 top-3 z-30 grid size-10 place-items-center rounded-md border border-[var(--border-subtle)] bg-[var(--elevated)] text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] md:hidden"
      >
        <Menu aria-hidden="true" className="size-5" />
      </button>

      {/* The rail surface stretches to the full page height while its content
          stays pinned to the viewport, so long pages never show the rail ending. */}
      <aside
        id="primary-sidebar"
        className={cn(
          "hidden min-h-screen shrink-0 self-stretch border-r border-[var(--border-subtle)] bg-[var(--elevated)] transition-[width] duration-200 motion-reduce:transition-none md:block",
          isCollapsed ? "w-16" : "w-60"
        )}
      >
        <div className="sticky top-0 flex h-screen flex-col overflow-hidden">
          {renderBrandRow(isCollapsed, toggleCollapsed)}

          <ProjectSelector collapsed={isCollapsed} {...projectSelection(pathname)} />

          <ProjectNav collapsed={isCollapsed} />

          <NavList collapsed={isCollapsed} />

          <div className="shrink-0 p-2">
            <SidebarAccountMenu key={menuKey} collapsed={isCollapsed} />
          </div>
        </div>
      </aside>

      {drawerOpen && renderDrawer(menuKey, drawerOpen, closeDrawer, pathname)}
    </>
  )
}

export type { TabId } from "../routes"
