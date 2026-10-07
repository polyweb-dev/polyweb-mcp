import { Button } from "@/shared/ui/button"

interface RestoreStatusViewProps {
  title: string
  detail: string
  /** Present only for a retryable failure. */
  onRetry?: (() => void) | undefined
  /** `alert` announces a failure; `status` announces progress. */
  live: "alert" | "status"
}

/** Accessible session-restore status and retry view of the workspace gate. */
export function RestoreStatusView({ title, detail, onRetry, live }: RestoreStatusViewProps) {
  return (
    <div
      className="flex min-h-screen items-center justify-center p-8"
      style={{ background: "var(--surface)", color: "var(--text)" }}
    >
      <div
        role={live}
        aria-live={live === "alert" ? "assertive" : "polite"}
        className="w-full max-w-sm rounded-md border border-[var(--border-subtle)] bg-[var(--elevated)] p-6"
      >
        <h1 className="text-[var(--text-strong)]">{title}</h1>
        <p className="mt-2 text-[13px] text-[var(--muted)]">{detail}</p>
        {onRetry !== undefined && (
          <div className="mt-4">
            <Button type="button" variant="outline" onClick={onRetry}>
              Retry
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
