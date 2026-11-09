import type { ReactNode } from "react"
import type { SelectOption } from "./selectTypes"

/** Default content of one select row and trigger: the icon, the label, then a muted description. */
export function selectRow(option: SelectOption): ReactNode {
  return (
    <span className="flex min-w-0 items-center gap-2">
      {option.icon !== undefined && (
        <span className="flex size-4 shrink-0 items-center justify-center">{option.icon}</span>
      )}
      <span className="truncate">{option.label}</span>
      {option.description !== undefined && (
        <span className="truncate text-[12px] text-[var(--muted)]">{option.description}</span>
      )}
    </span>
  )
}
