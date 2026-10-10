import type { FallbackConfig } from "@/domains/routing"
import { FailoverReadOnlyRow } from "./FailoverReadOnlyRow"

const READ_ONLY_NOTE = "Read-only for your role."

/** Read-only failover policy for a role without control-edit access. */
export function FailoverReadOnlyPanel({ config }: { config: FallbackConfig }) {
  return (
    <div className="rounded-lg border border-[var(--border-subtle)] p-4 space-y-4">
      <FailoverReadOnlyRow
        label="Fallback chaining"
        description={`Persisted backend policy. ${READ_ONLY_NOTE}`}
        value={config.enabled ? "Active" : "Single-shot"}
      />
      <div className="flex flex-col gap-3 pl-1 pt-1 border-t border-[var(--border-subtle)]">
        <FailoverReadOnlyRow
          label="Failover on rate limit (429)"
          description={`Session-only condition. ${READ_ONLY_NOTE}`}
          value={config.fallbackOnRateLimit ? "On" : "Off"}
        />
        <FailoverReadOnlyRow
          label="Failover on timeout"
          description={`Session-only condition. ${READ_ONLY_NOTE}`}
          value={config.fallbackOnTimeout ? "On" : "Off"}
        />
        <FailoverReadOnlyRow
          label="Failover on server error (5xx)"
          description={`Session-only condition. ${READ_ONLY_NOTE}`}
          value={config.fallbackOnServerError ? "On" : "Off"}
        />
      </div>
    </div>
  )
}
