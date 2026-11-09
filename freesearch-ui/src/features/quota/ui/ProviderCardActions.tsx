import type { ReactNode } from "react"
import { RefreshCw } from "lucide-react"
import { cn } from "cn"
import { Button } from "@/shared/ui/button"
import { formatDateTime } from "@/shared/lib/formatTime"

export type { CardModal } from "./ProviderCardMenu"

export interface ProviderCardActionsProps {
  providerName: string
  syncing: boolean
  onSync: () => void
  /** The provider reports no usage, so the refresh action stays off the card. */
  refreshSkipped?: boolean
  /** The plain result of the last refresh; it clears when the next refresh starts. */
  syncNote?: string | null
  updatedAt?: number | null
  /**
   * Composed OAuth control rendered inline after the refresh control.
   * Supplied by composition so the quota feature never imports the OAuth
   * feature directly.
   */
  oauthActions?: ReactNode
}

/**
 * The footer controls of one card: one Refresh button with the result of the
 * last refresh beside it, then the composed OAuth control. A provider without
 * a usage endpoint shows no Refresh, because there is nothing to refresh.
 */
export function ProviderCardActions({
  providerName,
  syncing,
  onSync,
  refreshSkipped = false,
  syncNote = null,
  updatedAt = null,
  oauthActions,
}: ProviderCardActionsProps): ReactNode {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-3">
      {!refreshSkipped && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={syncing}
          aria-label={"Refresh limits for " + providerName}
          onClick={onSync}
        >
          <RefreshCw
            aria-hidden="true"
            className={cn("size-3.5", syncing && "animate-spin motion-reduce:animate-none")}
          />
          {syncing ? "Refreshing…" : "Refresh"}
        </Button>
      )}
      {syncNote !== null && (
        <p role="status" title={updatedAt === null ? undefined : formatDateTime(new Date(updatedAt).toISOString())} className="min-w-0 text-[12px] text-[var(--muted)]">
          {syncNote}
        </p>
      )}
      {oauthActions}
    </div>
  )
}
