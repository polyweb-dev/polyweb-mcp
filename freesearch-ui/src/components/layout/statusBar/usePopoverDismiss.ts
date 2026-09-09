import { useEffect, type Dispatch, type RefObject, type SetStateAction } from "react"

export type OpenPopover = "providers" | "failover" | null

type SetOpenPopover = Dispatch<SetStateAction<OpenPopover>>

export function usePopoverDismiss(
  openPopover: OpenPopover,
  anchorRef: RefObject<HTMLDivElement | null>,
  providerTriggerRef: RefObject<HTMLButtonElement | null>,
  failoverTriggerRef: RefObject<HTMLButtonElement | null>,
  setOpenPopover: SetOpenPopover,
): void {
  useEffect(() => {
    if (!openPopover) return

    const closeOnOutside = (event: MouseEvent) => {
      if (!anchorRef.current?.contains(event.target as Node)) {
        setOpenPopover(null)
      }
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      const activeTrigger =
        openPopover === "providers"
          ? providerTriggerRef.current
          : failoverTriggerRef.current
      setOpenPopover(null)
      activeTrigger?.focus()
    }

    document.addEventListener("mousedown", closeOnOutside)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("mousedown", closeOnOutside)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [openPopover, anchorRef, providerTriggerRef, failoverTriggerRef, setOpenPopover])
}
