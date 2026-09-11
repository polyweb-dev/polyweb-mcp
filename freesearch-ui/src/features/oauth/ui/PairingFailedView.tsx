/** Terminal denial/expiry: what happened and how to retry. */
export function PairingFailedView({ kind }: { kind: "denied" | "expired" }) {
  const denied = kind === "denied"
  return (
    <div className="space-y-2" data-testid={"oauth-device-" + kind}>
      <p className="text-[13px] font-medium text-[var(--text-strong)]">
        {denied ? "Request denied." : "This code expired."}
      </p>
      <p
        role="alert"
        data-testid="oauth-device-error"
        className="text-[13px]"
        style={{ color: "var(--status-danger)" }}
      >
        {denied
          ? "The approval was denied in the browser. Get a new code to try again."
          : "This code expired before approval. Get a new code to try again."}
      </p>
    </div>
  )
}
