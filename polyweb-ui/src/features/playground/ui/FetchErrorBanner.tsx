import { AlertCircle } from "lucide-react"

export interface FetchErrorBannerProps {
  error: string
  onRetryWithFallback?: () => void
}

export function FetchErrorBanner({ error }: FetchErrorBannerProps) {
  const isBotBlocked = /bot.?blocked|blocked.*access|cloudflare|access denied|403/i.test(error)
  const isTimeout = /timed?\s*out|timeout/i.test(error)
  const isQuota = /quota|out of credits|402/i.test(error)

  const title = isBotBlocked
    ? "Target Site Access Blocked"
    : isTimeout
    ? "Fetch Request Timed Out"
    : isQuota
    ? "Provider Quota Exhausted"
    : "Document Fetch Failed"

  const suggestion = isBotBlocked
    ? "The target site (e.g., LinkedIn) restricts automated bots. Enable Chained Fallback or try an alternative provider."
    : isTimeout
    ? "The provider did not respond within 15 seconds. Try again or select another provider."
    : isQuota
    ? "The selected provider has no remaining credits. Check Settings > Quotas."
    : "The provider was unable to extract readable content from this URL."

  return (
    <div
      role="alert"
      data-testid="fetch-error-banner"
      className="flex flex-col gap-1.5 rounded-lg border border-[var(--status-danger)]/40 bg-[var(--surface)] p-3.5 text-[13px]"
    >
      <div className="flex items-center gap-2 font-medium" style={{ color: "var(--status-danger)" }}>
        <AlertCircle className="h-4 w-4 shrink-0" />
        <span>{title}</span>
      </div>
      <p className="text-[12px] text-[var(--foreground)]">{suggestion}</p>
      <p className="mt-1 font-mono text-[11px] text-[var(--muted)] break-all">{error}</p>
    </div>
  )
}
