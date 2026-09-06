import React from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { Switch } from "@/components/common/Switch"

/**
 * Failover policy: one master chaining switch over a vertical stack of
 * per-condition switches, plus the depth and timeout policy rows.
 */
export const SettingsFailover: React.FC = () => {
  const { fallbackConfig, updateFallbackConfig } = useFreeSearch()

  return (
    <section className="space-y-4 max-w-3xl">
      <div>
        <h3 className="text-[var(--text-strong)]">Failover policy</h3>
        <p className="text-[13px] text-[var(--muted)] mt-0.5">
          How the resolver reacts when a selected provider fails.
        </p>
      </div>

      <div className="rounded-lg border border-[var(--border-subtle)] p-4 space-y-4">
        <Switch
          checked={fallbackConfig.enabled}
          onChange={(checked) => updateFallbackConfig({ enabled: checked })}
          label="Fallback chaining"
          description={
            fallbackConfig.enabled
              ? "Cascades to the next ranked provider when the primary fails."
              : "Requests run single-shot against the selected provider."
          }
        />

        <div className="flex flex-col gap-3 pl-1 pt-1 border-t border-[var(--border-subtle)]">
          <Switch
            checked={fallbackConfig.fallbackOnRateLimit}
            onChange={(checked) => updateFallbackConfig({ fallbackOnRateLimit: checked })}
            label="Failover on rate limit (429)"
            description="Moves to the next provider when upstream returns HTTP 429."
          />
          <Switch
            checked={fallbackConfig.fallbackOnTimeout}
            onChange={(checked) => updateFallbackConfig({ fallbackOnTimeout: checked })}
            label="Failover on timeout"
            description="Moves on when a provider exceeds its hop time budget."
          />
          <Switch
            checked={fallbackConfig.fallbackOnServerError}
            onChange={(checked) => updateFallbackConfig({ fallbackOnServerError: checked })}
            label="Failover on server error (5xx)"
            description="Moves on when upstream reports a server-side failure."
          />
        </div>
      </div>

      <div className="rounded-lg border border-[var(--border-subtle)] px-4 divide-y divide-[var(--border-subtle)]">
        <div className="flex items-center justify-between py-3 gap-4">
          <span className="text-[13px] text-[var(--muted)]">Cascade depth</span>
          <span className="text-[13px] text-[var(--text)] tnum">
            {fallbackConfig.enabled
              ? `Up to ${fallbackConfig.maxAttempts} fallback hops`
              : "1 hop (single-shot)"}
          </span>
        </div>

        <div className="flex items-center justify-between py-3 gap-4">
          <span className="text-[13px] text-[var(--muted)]">Timeout budget</span>
          <span className="text-[13px] text-[var(--text)] tnum">3,000 ms</span>
        </div>
      </div>
    </section>
  )
}
