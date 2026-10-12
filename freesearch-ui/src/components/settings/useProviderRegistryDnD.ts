import { useState } from "react"

/**
 * Encapsulates HTML5 drag-and-drop state and reorder dispatch for the provider registry table.
 */
export function useProviderRegistryDnD(
  reorderPriority?: (sourceId: string, targetId: string) => Promise<void>,
) {
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dragOverId, setDragOverId] = useState<string | null>(null)

  const handleDragStart = (id: string, e: React.DragEvent) => {
    e.dataTransfer.setData("text/plain", id)
    e.dataTransfer.effectAllowed = "move"
    setDraggingId(id)
  }

  const handleDragOver = (id: string, e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = "move"
    if (dragOverId !== id) {
      setDragOverId(id)
    }
  }

  const handleDrop = async (targetId: string, e: React.DragEvent) => {
    e.preventDefault()
    const sourceId = e.dataTransfer.getData("text/plain") || draggingId
    setDraggingId(null)
    setDragOverId(null)
    if (sourceId && sourceId !== targetId && reorderPriority) {
      await reorderPriority(sourceId, targetId)
    }
  }

  const handleDragEnd = () => {
    setDraggingId(null)
    setDragOverId(null)
  }

  return {
    draggingId,
    dragOverId,
    handleDragStart,
    handleDragOver,
    handleDrop,
    handleDragEnd,
  }
}
