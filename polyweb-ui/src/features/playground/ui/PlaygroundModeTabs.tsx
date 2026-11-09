import { PillTabsList } from "@/shared/ui/PillTabsList"

/**
 * The Search | Fetch mode switch, the first control of each composer. It lives
 * inside the form, so Enter and Space activate the focused tab instead of
 * submitting the request.
 */
export function PlaygroundModeTabs() {
  return (
    <div
      className="shrink-0"
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          e.stopPropagation()
          ;(e.target as HTMLElement)?.click()
        }
      }}
    >
      <PillTabsList />
    </div>
  )
}
