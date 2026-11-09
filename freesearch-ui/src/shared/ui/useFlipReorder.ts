import { useLayoutEffect, useRef } from "react"

/** Move the final list as a unit, so rows cannot cross or overlap. */
export function useFlipReorder(key: string) {
  const ref = useRef<HTMLTableSectionElement>(null)
  const previous = useRef(key)
  useLayoutEffect(() => {
    if (previous.current === key) return
    previous.current = key
    const body = ref.current
    if (!body || typeof body.animate !== "function" || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return
    const animation = body.animate([{ transform: "translateY(4px)" }, { transform: "translateY(0)" }], { duration: 150, easing: "ease-out" })
    return () => animation.cancel()
  }, [key])
  return ref
}
