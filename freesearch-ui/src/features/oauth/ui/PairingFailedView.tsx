import { AlertCircle, Clock } from "lucide-react"

/** Terminal denial/expiry: what happened and how to retry. */
export function PairingFailedView({ kind }: { kind: "denied" | "expired" }) {
  const denied = kind === "denied"
  return (
    <div
      className="space-y-2 rounded-lg border border-[var(--status-danger)]/30 bg-[var(--surface)] p-3.5"
      data-testid={"oauth-device-" + kind}
    >
      <div className="flex items-center gap-2">
        {denied ? (
          <AlertCircle className="h-4 w-4 text-[var(--status-danger)] shrink-0" />
        ) : (
          <Clock className="h-4 w-4 text-[var(--status-warning)] shrink-0" />
        )}
        <p className="text-[13px] font-medium text-[var(--text-strong)]">
          {denied ? "Request denied." : "This code expired."}
        </p>
      </div>
      <p
        role="alert"
        data-testid="oauth-device-error"
        className="text-[12px] leading-relaxed pl-6"
        style={{ color: "var(--status-danger)" }}
      >
        {denied
          ? "The approval was denied in the browser. Get a new code to try again."
          : "This code expired before approval. Get a new code to try again."}
      </p>
    </div>
  )
}

