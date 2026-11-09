import { useEffect, useState } from "react"

/** True while the viewport matches the small-screen breakpoint where
 * pinned scroll scenes are disabled and content shows its finished state. */
export function useMobile(query = "(max-width: 640px)"): boolean {
  const [mobile, setMobile] = useState(
    () => window.matchMedia(query).matches
  )
  useEffect(() => {
    const mq = window.matchMedia(query)
    const onChange = () => setMobile(mq.matches)
    mq.addEventListener("change", onChange)
    return () => mq.removeEventListener("change", onChange)
  }, [query])
  return mobile
}
