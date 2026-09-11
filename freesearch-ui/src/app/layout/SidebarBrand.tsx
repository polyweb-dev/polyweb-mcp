import freesearchLogo from "@/assets/freesearch.webp"
import { cn } from "@/lib/utils"

interface BrandProps {
  collapsed?: boolean
}

export function Brand({ collapsed = false }: BrandProps) {
  return (
    <div className={cn("flex h-16 items-center", collapsed ? "justify-center" : "gap-3 px-4")}>
      <span className="grid size-8 shrink-0 place-items-center overflow-hidden rounded-md border border-[var(--border-subtle)] bg-[var(--secondary)]">
        <img
          src={freesearchLogo}
          alt=""
          aria-hidden="true"
          className="size-6 object-contain"
        />
      </span>
      {!collapsed && (
        <span className="text-[15px] font-semibold tracking-tight text-[var(--text-strong)]">
          FreeSearch
        </span>
      )}
    </div>
  )
}
