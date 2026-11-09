import React, { useEffect, useRef, useState } from "react"
import { apiService } from "@/services/api/polywebApi"
import { errorMessage } from "@/shared/api/http"
import { Field } from "@/shared/ui/Field"
import { fieldDescribedBy } from "@/shared/ui/fieldIds"
import { Select, type SelectOption } from "@/shared/ui/select"
import type { ProviderConfig } from "@/domains/providers"
import { toBackendId } from "@/domains/providers"

export interface TavilyRateTierSelectProps {
  provider: ProviderConfig
  /** False for a role without control-edit access: stored value as text only. */
  canEdit: boolean
  /** Post-save refresh of the provider status and the cached dashboard. */
  onUpdated: () => Promise<void>
  /** Card use only: short labels without numeric rate text. Settings keeps false. */
  compact?: boolean
  /** Confirmed dev/prod readback, called before the post-save refresh. */
  onConfirmed?: (environment: "dev" | "prod") => void
}

type KeyEnvironment = "dev" | "prod"

const TIER_NAMES: Record<KeyEnvironment, string> = {
  dev: "Development",
  prod: "Production",
}

/** The documented minute ceiling of each key environment. */
const TIER_RATES: Record<KeyEnvironment, string> = {
  dev: "100 requests per minute",
  prod: "1,000 requests per minute",
}

/** Keyless text without a numeric rate. */
const KEYLESS_TEXT = "Keyless access"

/** The dropdown declares the stored key environment, never a vendor-plan upgrade. */
const RATE_TIER_HINT = "The environment of the stored Tavily key. It does not change your Tavily plan."

const ACCESSIBLE_NAME = "Tavily rate tier (key environment)"
const CONTROL_ID = "tavily-rate-tier"
const READONLY_CLASS = "text-[12px] text-[var(--muted)]"

/** The card uses a compact field without numeric rate text. */
function tierControlPresentation(compact: boolean) {
  return compact
    ? { wrapper: "w-48 min-w-0", title: "Rate tier" }
    : { wrapper: "w-72 min-w-0", title: "Rate tier (key environment)" }
}

function isKeyEnvironment(value: string): value is KeyEnvironment {
  return value === "dev" || value === "prod"
}

/** The full text of one environment: "Development (100 requests per minute)". */
function fullTierText(environment: KeyEnvironment): string {
  return TIER_NAMES[environment] + " (" + TIER_RATES[environment] + ")"
}

/** The options of the control; a missing confirmed value adds a locked Unknown row. */
function tierOptions(compact: boolean, confirmed: KeyEnvironment | null): SelectOption[] {
  const options: SelectOption[] = (["dev", "prod"] as const).map((environment) => ({
    value: environment,
    label: TIER_NAMES[environment],
    ...(compact ? {} : { description: TIER_RATES[environment] }),
  }))
  if (confirmed === null) options.push({ value: "unknown", label: "Unknown" })
  return options
}

/**
 * Outcome of the last successful PATCH of this mount. `confirmed` carries the
 * environment read back from the response; `unconfirmed` marks a save whose
 * response carried no valid readback, locked to the stored value seen at save
 * time until a refreshed status supplies a different, valid value.
 */
type SaveResult =
  | { kind: "confirmed"; env: KeyEnvironment }
  | { kind: "unconfirmed"; storedAtSave: KeyEnvironment | null }

/** The confirmed environment to render, plus whether that confirmation is missing. */
function confirmedEnvironment(
  stored: KeyEnvironment | null,
  saveResult: SaveResult | null,
): { confirmed: KeyEnvironment | null; confirmationUnknown: boolean } {
  if (saveResult?.kind === "confirmed") {
    return { confirmed: saveResult.env, confirmationUnknown: false }
  }
  const unknown = saveResult?.kind === "unconfirmed" && stored === saveResult.storedAtSave
  return { confirmed: unknown ? null : stored, confirmationUnknown: unknown }
}

function rateTierText(confirmed: KeyEnvironment | null, compact: boolean): string {
  if (confirmed === null) return "Unknown"
  return compact ? TIER_NAMES[confirmed] : fullTierText(confirmed)
}

/** Read-only states share one small render path outside the editable field. */
function readOnlyTierControl(
  provider: ProviderConfig,
  canEdit: boolean,
  confirmed: KeyEnvironment | null,
  compact: boolean,
): React.ReactNode | null {
  if (provider.keyVaultStatus !== "configured") {
    return <span className={READONLY_CLASS}>{KEYLESS_TEXT}</span>
  }
  if (!canEdit) {
    return (
      <span className={READONLY_CLASS} title="Read-only for your role">
        {rateTierText(confirmed, compact)}
      </span>
    )
  }
  return null
}

/**
 * Tavily-only rate-tier control. One shared select edits the confirmed
 * `tavily_key_environment` through one partial PATCH;
 * every other provider renders nothing, and no inference from funds or key
 * text ever replaces the stored confirmed value.
 */
export const TavilyRateTierSelect: React.FC<TavilyRateTierSelectProps> = ({
  provider,
  canEdit,
  onUpdated,
  compact = false,
  onConfirmed,
}) => {
  const [saving, setSaving] = useState(false)
  const [saveResult, setSaveResult] = useState<SaveResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const presentation = tierControlPresentation(compact)
  // Obsolete-response guard: a request that settles after unmount or after a
  // credential replacement never writes state and never triggers the refresh.
  const mountedRef = useRef(true)
  const identityRef = useRef(provider.id + "|" + provider.keyVaultStatus)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])
  useEffect(() => {
    identityRef.current = provider.id + "|" + provider.keyVaultStatus
  }, [provider.id, provider.keyVaultStatus])

  const stored = provider.tavilyKeyEnvironment ?? null
  const { confirmed, confirmationUnknown } = confirmedEnvironment(stored, saveResult)

  const save = async (next: KeyEnvironment) => {
    const saveIdentity = identityRef.current
    const storedAtCall = stored
    setSaving(true)
    setError(null)
    try {
      const wire = await apiService.patchProvider(toBackendId(provider.id), {
        tavily_key_environment: next,
      })
      if (!mountedRef.current || identityRef.current !== saveIdentity) return
      const readback = wire.tavily_key_environment
      if (readback === "dev" || readback === "prod") {
        setSaveResult({ kind: "confirmed", env: readback })
        onConfirmed?.(readback)
      } else {
        setSaveResult({ kind: "unconfirmed", storedAtSave: storedAtCall })
      }
      try {
        await onUpdated()
      } catch {
        // The save is confirmed; a refresh failure surfaces through the
        // current provider/dashboard error surfaces, never as a save failure.
      }
    } catch (patchError) {
      if (!mountedRef.current || identityRef.current !== saveIdentity) return
      setError(errorMessage(patchError, "Unable to save the Tavily rate tier"))
    } finally {
      if (mountedRef.current) setSaving(false)
    }
  }

  const handleSelect = (next: string) => {
    if (!isKeyEnvironment(next)) return // Unknown is a display-only state, never a submit.
    if (next === confirmed) return // Unchanged selection: zero writes.
    void save(next)
  }

  const readOnlyControl = readOnlyTierControl(provider, canEdit, confirmed, compact)
  if (readOnlyControl !== null) return readOnlyControl
  const describedBy = fieldDescribedBy(CONTROL_ID, confirmationUnknown, error)
  return (
    <div className={presentation.wrapper} title={RATE_TIER_HINT}>
      <Field
        id={CONTROL_ID}
        label={presentation.title}
        hint={confirmationUnknown ? "Confirmation unavailable" : undefined}
        error={error}
      >
        <Select
          id={CONTROL_ID}
          ariaLabel={ACCESSIBLE_NAME}
          value={confirmed ?? "unknown"}
          options={tierOptions(compact, confirmed)}
          onValueChange={handleSelect}
          disabled={saving || confirmed === null}
          invalid={error !== null}
          {...(describedBy !== undefined ? { ariaDescribedBy: describedBy } : {})}
        />
      </Field>
    </div>
  )
}
