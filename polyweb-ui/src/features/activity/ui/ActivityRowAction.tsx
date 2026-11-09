import { ChevronRight } from "lucide-react"
import { Button } from "@/shared/ui/button"

/**
 * The trailing "View details" button of one Activity row. Its overlay covers
 * the whole row (the row must be `relative`), so clicking anywhere on the row
 * presses this one button and keyboard focus rings the whole row.
 */
export function ActivityRowAction({ onOpen }: { onOpen: () => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label="View details"
      title="View details"
      onClick={(event) => {
        // The row is a click target too: stop the bubble so one interaction
        // opens the trace exactly once.
        event.stopPropagation()
        onOpen()
      }}
      className="text-[var(--muted)] after:absolute after:inset-0 after:content-[''] focus-visible:ring-0 focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-[var(--signal)]/40"
    >
      <ChevronRight aria-hidden="true" className="size-4" />
    </Button>
  )
}
