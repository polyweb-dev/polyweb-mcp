import { useLayoutEffect, useState } from "react"
import type { CSSProperties, RefObject } from "react"

export interface ListPlacement {
  host: Element
  style: CSSProperties
}

/**
 * Inside a dialog the list renders into the dialog popup, outside its
 * scrolling body, so the body never clips it and the dialog still counts a
 * click on it as inside. It opens below the trigger, or above when the space
 * below is short. Outside a dialog this returns `null` and the list renders
 * in place under the trigger.
 */
export function useListPlacement(
  open: boolean,
  triggerRef: RefObject<HTMLButtonElement | null>
): ListPlacement | null {
  const [placement, setPlacement] = useState<ListPlacement | null>(null)
  useLayoutEffect(() => {
    const trigger = triggerRef.current
    const host = open && trigger !== null ? trigger.closest('[data-slot="dialog-content"]') : null
    if (host === null || trigger === null) {
      setPlacement(null)
      return
    }
    const t = trigger.getBoundingClientRect()
    const h = host.getBoundingClientRect()
    const below = window.innerHeight - t.bottom - 16
    const above = t.top - 16
    const flip = below < 200 && above > below
    const style: CSSProperties = {
      position: "absolute",
      left: t.left - h.left,
      minWidth: t.width,
      maxHeight: Math.min(320, flip ? above : below),
      ...(flip ? { bottom: h.bottom - t.top + 4 } : { top: t.bottom - h.top + 4 }),
    }
    setPlacement({ host, style })
  }, [open, triggerRef])
  return placement
}
