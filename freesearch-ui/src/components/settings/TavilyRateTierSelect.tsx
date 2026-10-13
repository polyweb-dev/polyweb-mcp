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
}

type KeyEnvironment = "dev" | "prod"

const RATE_TIER_LABELS: Record<KeyEnvironment, string> = {
  dev: "Development — 100 requests/min",
  prod: "Production — 1000 requests/min",
}

/** The dropdown declares the stored key environment, never a vendor-plan upgrade. */
const RATE_TIER_HINT =
  "Declares the current key environment of the stored Tavily key, not a vendor-plan upgrade."

/** Same native select tokens as the other settings inputs (compact cell size). */
const SELECT_CLASS =
  "rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1 text-[12px] text-[var(--text)] outline-none focus-visible:border-[var(--signal)] disabled:opacity-60"

const READONLY_CLASS = "text-[12px] text-[var(--muted)]"

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

function rateTierText(confirmed: KeyEnvironment | null): string {
  return confirmed === null ? "Unknown" : RATE_TIER_LABELS[confirmed]
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
}) => {
  const [saving, setSaving] = useState(false)
  const [saveResult, setSaveResult] = useState<SaveResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Obsolete-response guard: a request that settles after unmount never
  // writes state and never triggers the post-save refresh.
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const stored = provider.tavilyKeyEnvironment ?? null
  const { confirmed, confirmationUnknown } = confirmedEnvironment(stored, saveResult)

  const save = async (next: KeyEnvironment) => {
    setSaving(true)
    setError(null)
    try {
      const wire = await apiService.patchProvider(toBackendId(provider.id), {
        tavily_key_environment: next,
      })
      if (!mountedRef.current) return
      const readback = wire.tavily_key_environment
      setSaveResult(
        readback === "dev" || readback === "prod"
          ? { kind: "confirmed", env: readback }
          : { kind: "unconfirmed", storedAtSave: stored },
      )
      try {
        await onUpdated()
      } catch {
        // The save is confirmed; a refresh failure surfaces through the
        // current provider/dashboard error surfaces, never as a save failure.
      }
    } catch (patchError) {
      if (!mountedRef.current) return
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

  if (provider.keyVaultStatus !== "configured") {
    return (
      <span className={READONLY_CLASS} title="Keyless — numeric rate unknown">
        Keyless — numeric rate unknown
      </span>
    )
  }
  if (!canEdit) {
    return (
      <span className={READONLY_CLASS} title="Read-only for your role">
        {rateTierText(confirmed)}
      </span>
    )
  }
  return (
    <div className="min-w-[200px]" title={RATE_TIER_HINT}>
      <label htmlFor="tavily-rate-tier" className="mb-1 block text-[12px] text-[var(--muted)]">
        Rate tier (key environment)
      </label>
      <select
        id="tavily-rate-tier"
        aria-label="Tavily rate tier (key environment)"
        value={confirmed ?? "unknown"}
        onChange={handleSelect}
        disabled={saving || confirmed === null}
        className={SELECT_CLASS}
      >
        <option value="dev">{RATE_TIER_LABELS.dev}</option>
        <option value="prod">{RATE_TIER_LABELS.prod}</option>
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
