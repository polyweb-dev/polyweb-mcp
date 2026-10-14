import React, { useEffect, useRef, useState } from "react"
import { apiService } from "@/services/api/freesearchApi"
import { errorMessage } from "@/shared/api/http"
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

const RATE_TIER_LABELS: Record<KeyEnvironment, string> = {
  dev: "Development — 100 requests per minute",
  prod: "Production — 1000 requests per minute",
}

/** Card-only short labels without numeric rate counts. */
const COMPACT_TIER_LABELS: Record<KeyEnvironment, string> = {
  dev: "Development",
  prod: "Production",
}

/** Compact keyless text without a numeric rate. */
const COMPACT_KEYLESS_TEXT = "Keyless access"

/** The dropdown declares the stored key environment, never a vendor-plan upgrade. */
const RATE_TIER_HINT =
  "Declares the current key environment of the stored Tavily key, not a vendor-plan upgrade."

/** Same native select tokens as the other settings inputs (compact cell size). */
const SELECT_BASE =
  "rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1 text-[12px] outline-none focus-visible:border-[var(--signal)] disabled:opacity-60"
const SELECT_CLASS = SELECT_BASE + " text-[var(--text)]"
const COMPACT_SELECT_CLASS = SELECT_BASE + " text-[var(--text-strong)]"
const LABEL_CLASS = "mb-1 block text-[12px] text-[var(--muted)]"
const COMPACT_LABEL_CLASS = "mb-1 block text-[12px] text-[var(--text-strong)]"

const READONLY_CLASS = "text-[12px] text-[var(--muted)]"

/** The card uses a compact field with the strong label color of the Credits title. */
function tierControlPresentation(compact: boolean) {
  return compact
    ? {
        wrapper: "w-fit min-w-0",
        label: COMPACT_LABEL_CLASS,
        select: COMPACT_SELECT_CLASS,
        title: "Rate tier",
      }
    : {
        wrapper: "min-w-[200px]",
        label: LABEL_CLASS,
        select: SELECT_CLASS,
        title: "Rate tier (key environment)",
      }
}

function isKeyEnvironment(value: string): value is KeyEnvironment {
  return value === "dev" || value === "prod"
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
  return compact ? COMPACT_TIER_LABELS[confirmed] : RATE_TIER_LABELS[confirmed]
}

/** Read-only states share one small render path outside the editable field. */
function readOnlyTierControl(
  provider: ProviderConfig,
  canEdit: boolean,
  confirmed: KeyEnvironment | null,
  compact: boolean,
): React.ReactNode | null {
  if (provider.keyVaultStatus !== "configured") {
    const keylessText = compact ? COMPACT_KEYLESS_TEXT : "Keyless — numeric rate unknown"
    return <span className={READONLY_CLASS} title={keylessText}>{keylessText}</span>
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
 * Tavily-only rate-tier control for the Settings registry. One native select
 * edits the confirmed `tavily_key_environment` through one partial PATCH;
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

  const handleSelect = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const next = event.target.value
    if (!isKeyEnvironment(next)) return // Unknown is a display-only state, never a submit.
    if (next === confirmed) return // Unchanged selection: zero writes.
    void save(next)
  }

  const readOnlyControl = readOnlyTierControl(provider, canEdit, confirmed, compact)
  if (readOnlyControl !== null) return readOnlyControl
  return (
    <div className={presentation.wrapper} title={RATE_TIER_HINT}>
      <label htmlFor="tavily-rate-tier" className={presentation.label}>
        {presentation.title}
      </label>
      <select
        id="tavily-rate-tier"
        aria-label="Tavily rate tier (key environment)"
        value={confirmed ?? "unknown"}
        onChange={handleSelect}
        disabled={saving || confirmed === null}
        className={presentation.select}
      >
        <option value="dev">{compact ? COMPACT_TIER_LABELS.dev : RATE_TIER_LABELS.dev}</option>
        <option value="prod">{compact ? COMPACT_TIER_LABELS.prod : RATE_TIER_LABELS.prod}</option>
        {confirmed === null && <option value="unknown">Unknown</option>}
      </select>
      {confirmationUnknown && (
        <p className="mt-1 text-[12px] text-[var(--muted)]">Confirmation unavailable</p>
      )}
      {error && (
        <p role="alert" className="mt-1 text-[12px] text-[var(--status-danger)]">
          {error}
        </p>
      )}
    </div>
  )
}
