import type { DragEvent } from "react"
import { ArrowDown, ArrowUp, GripVertical } from "lucide-react"
import { Button } from "./button"

export function ReorderHandle(props: {
  label: string
  rank: number
  count: number
  canEdit: boolean
  pending: boolean
  onDragStart: (event: DragEvent) => void
  onDragEnd: () => void
  onMove: (direction: "up" | "down") => void
}) {
  const { label, rank, count, canEdit, pending, onDragStart, onDragEnd, onMove } = props
  const number = <span className="min-w-5 text-center text-[var(--muted)] tnum" title={`Dispatch order ${rank} of ${count}`}>{rank}</span>
  if (!canEdit) return number
  return (
    <div className="flex items-center gap-1">
      <span role="img" aria-label={`Drag ${label} to change priority`} title={`Drag ${label} to change priority`}
        draggable={!pending} onDragStart={onDragStart} onDragEnd={onDragEnd} className="cursor-grab text-[var(--muted)]">
        <GripVertical aria-hidden="true" className="size-3.5" />
      </span>
      <Button type="button" variant="ghost" size="icon-xs" aria-label={`Move ${label} priority up`}
        disabled={pending || rank === 1} onClick={() => onMove("up")}><ArrowUp aria-hidden="true" className="size-3" /></Button>
      {number}
      <Button type="button" variant="ghost" size="icon-xs" aria-label={`Move ${label} priority down`}
        disabled={pending || rank === count} onClick={() => onMove("down")}><ArrowDown aria-hidden="true" className="size-3" /></Button>
    </div>
  )
}
