import { useCallback, useEffect, useRef, useState } from "react"

const STORAGE_KEY = "freesearch.sidebar.collapsed"

function readStoredCollapsed(defaultValue: boolean): boolean {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === null) return defaultValue
    if (stored === "1") return true
    if (stored === "0") return false
    return defaultValue
  } catch {
    return defaultValue
  }
}

export interface SidebarStateOptions {
  collapsed?: boolean
  defaultCollapsed: boolean
  onCollapsedChange?: (collapsed: boolean) => void
}

/**
 * Collapse persistence plus the mobile drawer lifecycle (Escape to close
 * with focus return). Rendering stays in the Sidebar component.
 */
export function useSidebarState({
  collapsed,
  defaultCollapsed,
  onCollapsedChange,
}: SidebarStateOptions) {
  const isControlled = collapsed !== undefined
  const [internalCollapsed, setInternalCollapsed] = useState(() =>
    readStoredCollapsed(defaultCollapsed)
  )
  const [drawerOpen, setDrawerOpen] = useState(false)
  const openerRef = useRef<HTMLButtonElement>(null)
  const isCollapsed = isControlled ? collapsed : internalCollapsed

  const closeDrawer = useCallback((returnFocus = false) => {
    setDrawerOpen(false)
    if (returnFocus) openerRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!drawerOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDrawer(true)
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [closeDrawer, drawerOpen])

  const openDrawer = useCallback(() => {
    setDrawerOpen(true)
  }, [])

  const toggleCollapsed = useCallback(() => {
    const next = !isCollapsed
    if (!isControlled) {
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0")
      } catch {
        // Persistence is best-effort; the control must remain usable.
      }
    }
    setInternalCollapsed(next)
    onCollapsedChange?.(next)
  }, [isCollapsed, isControlled, onCollapsedChange])

  return {
    isCollapsed,
    drawerOpen,
    openerRef,
    openDrawer,
    closeDrawer,
    toggleCollapsed,
  }
}
