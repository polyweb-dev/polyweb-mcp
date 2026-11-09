import { useId, useState } from "react"
import type { ReactNode } from "react"
import { ChevronRight } from "lucide-react"
import { cn } from "cn"

interface AdvancedSectionProps {
  label: string
  forceOpen?: boolean
  children: ReactNode
}

export function AdvancedSection({ label, forceOpen = false, children }: AdvancedSectionProps) {
  const [toggled, setToggled] = useState(false)
  const open = toggled || forceOpen
  const bodyId = useId()
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? bodyId : undefined}
        onClick={() => setToggled(!open)}
        className="-ml-1 inline-flex h-8 items-center gap-1.5 rounded-md px-1 text-[13px] font-medium text-[var(--text)] transition-colors hover:text-[var(--text-strong)] focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 focus-visible:outline-none"
      >
        <ChevronRight aria-hidden="true" className={cn("size-4 text-[var(--muted)] transition-transform motion-reduce:transition-none", open && "rotate-90")} />
        {label}
      </button>
      {open && <div id={bodyId} className="mt-3 space-y-4">{children}</div>}
    </div>
  )
}
