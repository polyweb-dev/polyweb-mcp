import React from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { Section } from "@/shared/ui/Section"
import { Switch } from "@/shared/ui/Switch"
import { FailoverPolicyRow } from "./FailoverPolicyRow"
import { MaxAttemptsControl } from "./MaxAttemptsControl"

const FALLBACK_DESCRIPTION = "Try the next provider in the project order"
const ATTEMPTS_DESCRIPTION = "Number of providers for each request, first provider included"
const SINGLE_ATTEMPT_NOTE = "Off: each request tries one provider"

/**
 * The installation's fallback policy, shown once under the provider table.
 * Only what the backend saves and enforces appears: Fallback on or off, and
 * Max attempts while it is on. A role without control-edit access sees the
 * same two cells as plain values.
 */
export const SettingsFailover: React.FC = () => {
  const { fallbackConfig, updateFallbackConfig, canEditControls } = useFreeSearch()
  const { enabled, maxAttempts } = fallbackConfig

  return (
    <Section title="When a provider fails" panel className="w-full max-w-none">
      <div className="grid grid-cols-2 divide-x divide-[var(--border-subtle)]">
        <FailoverPolicyRow label="Fallback" description={FALLBACK_DESCRIPTION}>
          {canEditControls ? (
            <Switch
              checked={enabled}
              onChange={(checked) => void updateFallbackConfig({ enabled: checked })}
              ariaLabel="Fallback"
            />
          ) : (
            enabled ? "On" : "Off"
          )}
        </FailoverPolicyRow>
        {enabled ? (
          <FailoverPolicyRow label="Max attempts" description={ATTEMPTS_DESCRIPTION}>
            {canEditControls ? (
              <MaxAttemptsControl
                value={maxAttempts}
                onChange={(next) => void updateFallbackConfig({ maxAttempts: next })}
              />
            ) : (
              maxAttempts
            )}
          </FailoverPolicyRow>
        ) : (
          <p className="flex items-center px-5 py-4 text-[13px] text-[var(--muted)]">{SINGLE_ATTEMPT_NOTE}</p>
        )}
      </div>
    </Section>
  )
}
