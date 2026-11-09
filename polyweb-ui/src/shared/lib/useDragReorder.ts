import { useState } from "react"
import type { DragEvent } from "react"

export function useDragReorder(
  moveProvider: (sourceId: string, targetId: string) => Promise<void>,
) {
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [targetId, setTargetId] = useState<string | null>(null)

  const clearDrag = () => {
    setDraggingId(null)
    setTargetId(null)
  }

  const startDrag = (id: string, event: DragEvent) => {
    event.dataTransfer.setData("text/plain", id)
    event.dataTransfer.effectAllowed = "move"
    setDraggingId(id)
  }

  const dragOver = (id: string, event: DragEvent) => {
    if (!draggingId) return
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    setTargetId(id === draggingId ? null : id)
  }

  const drop = (id: string, event: DragEvent) => {
    if (!draggingId) return
    event.preventDefault()
    clearDrag()
    if (draggingId !== id) void moveProvider(draggingId, id)
  }

  const leaveList = (event: DragEvent) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setTargetId(null)
  }

  return { draggingId, targetId, startDrag, dragOver, drop, clearDrag, leaveList }
}
