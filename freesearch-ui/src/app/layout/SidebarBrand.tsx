import { PanelLeftOpen } from "lucide-react"
import freesearchLogo from "@/assets/freesearch.webp"
import { cn } from "cn"

interface BrandProps {
  collapsed?: boolean
  onExpand?: () => void
}

/**
 * FreeSearch brand of the sidebar header.
 *
 * The expanded form is static. The collapsed form with an `onExpand` callback
 * is one native button: the logo shows at pointer idle, and the expansion icon
 * replaces it on pointer rest or keyboard focus. The CSS group supplies both
 * states, so Enter, Space, and touch need no prior hover. Both icons occupy the
 * same grid cell, so the reveal moves no geometry.
 */
export function Brand({ collapsed = false, onExpand }: BrandProps) {
  const mark = (
    <span className="grid size-8 shrink-0 place-items-center overflow-hidden rounded-md border border-[var(--border-subtle)] bg-[var(--secondary)]">
      <img
        src={freesearchLogo}
        alt=""
        aria-hidden="true"
        className="size-6 object-contain"
      />
    </span>
  )

  if (collapsed && onExpand !== undefined) {
    return (
      <div className="flex h-16 shrink-0 items-center justify-center">
        <button
          type="button"
          aria-label="Expand sidebar"
          title="Expand sidebar"
          aria-expanded={false}
          aria-controls="primary-sidebar"
          onClick={onExpand}
          className="group grid size-9 shrink-0 place-items-center rounded-md transition-colors hover:bg-[var(--secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] motion-reduce:transition-none"
        >
          <span className="col-start-1 row-start-1 grid place-items-center transition-opacity group-hover:opacity-0 group-focus-visible:opacity-0 motion-reduce:transition-none">
            {mark}
          </span>
          <PanelLeftOpen
            aria-hidden="true"
            className="col-start-1 row-start-1 size-[18px] text-[var(--muted)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none"
          />
        </button>
      </div>
    )
  }

  return (
    <div className={cn("flex h-16 items-center", collapsed ? "justify-center" : "gap-3 px-4")}>
      {mark}
      {!collapsed && (
        <span className="text-[15px] font-semibold tracking-tight text-[var(--text-strong)]">
          FreeSearch
        </span>
      )}
    </div>
  )
}
