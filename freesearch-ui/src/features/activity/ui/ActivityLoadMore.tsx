import { Button } from "@/shared/ui/button"
import type { ActivityController } from "../model/useActivityController"

/** "Load more" control of the cursor pages, with its own failure line. */
export function ActivityLoadMore({ controller }: { controller: ActivityController }) {
  if (!controller.hasMore) return null
  return (
    <div className="flex flex-col items-center gap-2">
      {controller.moreStatus === "error" && (
        <p role="alert" className="text-[13px]" style={{ color: "var(--status-danger)" }}>
          More traces unavailable — {controller.moreError}
        </p>
      )}
      <Button
        variant="outline"
        size="sm"
        disabled={controller.moreStatus === "loading"}
        onClick={controller.loadMore}
      >
        {controller.moreStatus === "loading" ? "Loading more..." : "Load more"}
      </Button>
    </div>
  )
}
