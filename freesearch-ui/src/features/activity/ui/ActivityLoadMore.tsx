import { Button } from "@/shared/ui/button"
import type { ActivityController } from "../model/useActivityController"

/** "Showing 50 traces · more available" when the cursor has another page. */
function countText(count: number, hasMore: boolean): string {
  const noun = count === 1 ? "trace" : "traces"
  return `Showing ${count.toLocaleString("en-US")} ${noun}${hasMore ? " · more available" : ""}`
}

/** Footer of the Activity list: how many traces are loaded, and "Load more" when the cursor has more. */
export function ActivityLoadMore({ controller }: { controller: ActivityController }) {
  return (
    <div className="flex flex-col items-center gap-2">
      <p className="text-[12px] text-[var(--muted)] tnum">
        {countText(controller.summaries.length, controller.hasMore)}
      </p>
      {controller.moreStatus === "error" && (
        <p role="alert" className="text-[13px]" style={{ color: "var(--status-danger)" }}>
          Couldn't load more traces: {controller.moreError}
        </p>
      )}
      {controller.hasMore && (
        <Button
          variant="outline"
          size="form"
          disabled={controller.moreStatus === "loading"}
          onClick={controller.loadMore}
        >
          {controller.moreStatus === "loading" ? "Loading more..." : "Load more"}
        </Button>
      )}
    </div>
  )
}
