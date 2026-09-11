import { Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Brand } from "./SidebarBrand"
import { NavList } from "./SidebarNavList"
import { useSidebarState } from "./useSidebarState"

export interface SidebarProps {
  collapsed?: boolean
  defaultCollapsed?: boolean
  onCollapsedChange?: (collapsed: boolean) => void
}

export function Sidebar({
  collapsed,
  defaultCollapsed = false,
  onCollapsedChange,
}: SidebarProps) {
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

      <aside
        id="primary-sidebar"
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col overflow-hidden border-r border-[var(--border-subtle)] bg-[var(--elevated)] transition-[width] duration-200 motion-reduce:transition-none md:flex",
          isCollapsed ? "w-16" : "w-60"
        )}
      >
        <Brand collapsed={isCollapsed} />
        <NavList collapsed={isCollapsed} />
        <button
          type="button"
          aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!isCollapsed}
          aria-controls="primary-sidebar"
          onClick={toggleCollapsed}
          className={cn(
            "m-2 flex h-10 items-center rounded-md text-[13px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--secondary)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] motion-reduce:transition-none",
            isCollapsed ? "justify-center" : "gap-3 px-3"
          )}
        >
          {isCollapsed ? (
            <PanelLeftOpen aria-hidden="true" className="size-[18px]" />
          ) : (
            <>
              <PanelLeftClose aria-hidden="true" className="size-[18px]" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label="Dismiss navigation overlay"
            data-testid="sidebar-scrim"
            onClick={() => closeDrawer(true)}
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
              <button
                type="button"
                aria-label="Close navigation"
                onClick={() => closeDrawer(true)}
                className="grid size-9 place-items-center rounded-md text-[var(--muted)] hover:bg-[var(--secondary)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]"
              >
                <X aria-hidden="true" className="size-5" />
              </button>
            </div>
            <NavList collapsed={false} onNavigate={() => closeDrawer()} />
          </div>
        </div>
      )}
    </>
  )
}

export type { TabId } from "../routes"
