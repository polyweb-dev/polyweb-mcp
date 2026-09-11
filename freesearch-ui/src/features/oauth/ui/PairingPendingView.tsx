import { Button } from "@/components/ui/button"
import { cn } from "cn"
import { buttonVariants } from "@/components/ui/button"
import { formatCountdown } from "../model/pairingFlow"

export interface PairingPendingViewProps {
  userCode: string
  approvalUrl: string | null
  totalSec: number
  remainingSec: number
  copied: boolean
  onCopy: () => void
}

/** Pending state: device code plus the approval link and countdown. */
export function PairingPendingView({
  userCode,
  approvalUrl,
  totalSec,
  remainingSec,
  copied,
  onCopy,
}: PairingPendingViewProps) {
  return (
    <div className="space-y-3">
      <div>
        <p id="oauth-device-code-label" className="text-[12px] text-[var(--muted)] mb-1">
          Enter this code in your browser
        </p>
        <div className="flex items-center gap-2">
          <p
            data-testid="oauth-device-user-code"
            aria-labelledby="oauth-device-code-label"
            className="flex-1 rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-3 py-2 text-center text-[20px] font-semibold tracking-[0.2em] text-[var(--text-strong)] tnum select-all"
          >
            {userCode}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="oauth-device-copy"
            onClick={onCopy}
          >
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {approvalUrl && (
          <a
            data-testid="oauth-device-open-verification"
            href={approvalUrl}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: "default", size: "sm" }))}
          >
            Open Parallel approval
          </a>
        )}
        <span
          role="progressbar"
          aria-label="Time left to approve"
          aria-valuemin={0}
          aria-valuemax={Math.max(1, totalSec)}
          aria-valuenow={remainingSec}
          data-testid="oauth-device-countdown"
          className="text-[12px] text-[var(--muted)] tnum"
        >
          Expires in {formatCountdown(remainingSec)}
        </span>
      </div>
      <p className="text-[12px] text-[var(--muted)]">
        Waiting for approval. This closes on its own once you approve.
      </p>
    </div>
  )
}

