import { Button, buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Check, Copy, ExternalLink, Clock } from "lucide-react"
import { formatCountdown } from "../model/pairingFlow"

export interface PairingPendingViewProps {
  userCode: string
  approvalUrl: string | null
  totalSec: number
  remainingSec: number
  copied: boolean
  onCopy: () => void
  providerName?: string
}

/** Pending state: device code plus the approval link and countdown. */
export function PairingPendingView({
  userCode,
  approvalUrl,
  totalSec,
  remainingSec,
  copied,
  onCopy,
  providerName = "Parallel",
}: PairingPendingViewProps) {
  const progressPercent = Math.max(0, Math.min(100, (remainingSec / Math.max(1, totalSec)) * 100))

  return (
    <div className="space-y-4">
      {/* Step 1: Code display */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label id="oauth-device-code-label" className="text-[12px] font-medium text-[var(--text-strong)]">
            1. Copy your code
          </label>
          <span className="text-[11px] text-[var(--muted)]">Enter this code in your browser</span>
        </div>
        <div className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] p-2 pl-4 transition-all focus-within:border-[var(--signal)]">
          <p
            data-testid="oauth-device-user-code"
            aria-labelledby="oauth-device-code-label"
            className="font-mono text-[20px] font-bold tracking-[0.22em] text-[var(--text-strong)] tnum select-all"
          >
            {userCode}
          </p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="oauth-device-copy"
            onClick={onCopy}
            className="h-8 gap-1.5 px-3 text-[12px] font-medium bg-[var(--elevated)] hover:bg-[var(--elevated)]/80 text-[var(--text-strong)] border border-[var(--border-subtle)] shadow-xs"
          >
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5 text-[var(--status-healthy)]" />
                <span className="text-[var(--status-healthy)]">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5 text-[var(--muted)]" />
                <span>Copy</span>
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Step 2: Open link and countdown */}
      <div className="space-y-2">
        <label className="text-[12px] font-medium text-[var(--text-strong)] block">
          2. Authorize in browser
        </label>
        {approvalUrl && (
          <a
            data-testid="oauth-device-open-verification"
            href={approvalUrl}
            target="_blank"
            rel="noreferrer"
            className={cn(
              buttonVariants({ variant: "default", size: "default" }),
              "w-full flex items-center justify-center gap-2 text-[13px] font-medium bg-[var(--signal)] hover:bg-[var(--signal)]/90 text-white h-10 shadow-sm transition-all"
            )}
          >
            <span>Open {providerName} approval</span>
            <ExternalLink className="h-4 w-4 opacity-80" />
          </a>
        )}
        <div className="space-y-1.5 pt-0.5">
          <div className="flex items-center justify-between text-[12px] text-[var(--muted)]">
            <div className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-[var(--muted)]" />
              <span
                role="progressbar"
                aria-label="Time left to approve"
                aria-valuemin={0}
                aria-valuemax={Math.max(1, totalSec)}
                aria-valuenow={remainingSec}
                data-testid="oauth-device-countdown"
                className="tnum font-medium"
              >
                Expires in {formatCountdown(remainingSec)}
              </span>
            </div>
            <span className="text-[11px] text-[var(--muted)]/80">Auto-expires</span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-[var(--surface)]">
            <div
              className="h-full bg-[var(--signal)] transition-all duration-1000 ease-linear rounded-full"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      </div>

      {/* Status banner */}
      <div className="flex items-center gap-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)]/60 px-3 py-2.5 text-[12px] text-[var(--muted)]">
        <span className="relative flex h-2 w-2 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--signal)] opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--signal)]" />
        </span>
        <p className="leading-snug">
          Waiting for approval. This closes on its own once you approve.
        </p>
      </div>
    </div>
  )
}


