import type { FallbackConfig } from "@/domains/routing"

export const FAILOVER_POPOVER_ID = "failover-status-details"

interface FailoverStatusPopoverProps {
  fallbackConfig: FallbackConfig
  failoverStatus: string
}

export function FailoverStatusPopover({
  fallbackConfig,
  failoverStatus,
}: FailoverStatusPopoverProps) {
  return (
    <section
      id={FAILOVER_POPOVER_ID}
      role="dialog"
      aria-label="Failover settings details"
      className="absolute bottom-full right-2 mb-1.5 w-72 rounded-md border border-[var(--border-subtle)] bg-[var(--elevated)] p-3 text-[12px] text-[var(--text)] shadow-xl"
    >
      <div className="flex items-center justify-between border-b border-[var(--border-subtle)] pb-2">
        <strong className="font-medium text-[var(--text-strong)]">Failover settings</strong>
        <span
          className={
            fallbackConfig.enabled
              ? "font-medium text-[var(--status-healthy)]"
              : "text-[var(--muted)]"
          }
        >
          {failoverStatus}
        </span>
      </div>
      <div className="space-y-2 py-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[var(--muted)]">Fallback chaining</span>
          <span className="text-[var(--text-strong)]">
            {fallbackConfig.enabled ? "Chained (active)" : "Single-shot"}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-[var(--muted)]">Cascade depth</span>
          <span className="text-[var(--text-strong)] tnum">
            {fallbackConfig.enabled
              ? `Up to ${fallbackConfig.maxAttempts} hops`
              : "1 hop"}
          </span>
        </div>
        <div className="border-t border-[var(--border-subtle)] pt-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-[var(--muted)]">
          Conditions
        </div>
        <div className="flex items-center justify-between gap-2">
          <span>Rate limit (429)</span>
          <span
            className={
              fallbackConfig.fallbackOnRateLimit
                ? "text-[var(--status-healthy)]"
                : "text-[var(--muted)]"
            }
          >
            {fallbackConfig.fallbackOnRateLimit ? "Enabled" : "Disabled"}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span>Timeout</span>
          <span
            className={
              fallbackConfig.fallbackOnTimeout
                ? "text-[var(--status-healthy)]"
                : "text-[var(--muted)]"
            }
          >
            {fallbackConfig.fallbackOnTimeout ? "Enabled" : "Disabled"}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span>Server error (5xx)</span>
          <span
            className={
              fallbackConfig.fallbackOnServerError
                ? "text-[var(--status-healthy)]"
                : "text-[var(--muted)]"
            }
          >
            {fallbackConfig.fallbackOnServerError ? "Enabled" : "Disabled"}
          </span>
        </div>
      </div>
    </section>
  )
}
