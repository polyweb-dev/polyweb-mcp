import { useState } from "react"
import type { FormEvent, ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import type { CRDGrantPayload, CRDGrantsSummary } from "@/domains/dashboard"
import { formatCRDAmount } from "../model/crdDisplay"

export interface CRDGrantFormProps {
  providerName: string
  authMode: string
  grants: CRDGrantsSummary | null
  fetchAvailable: boolean
  saving: boolean
  saveError: string | null
  staleVersion: boolean
  onSave: (payload: CRDGrantPayload) => Promise<void>
  onReload: () => void
}

interface GrantDraft {
  search: string
  fetch: string
  start: string
  end: string
}

interface GrantField {
  name: keyof GrantDraft
  label: string
  type: string
  disabled: boolean
}

type GrantErrors = Partial<Record<keyof GrantDraft, string>>

/** Operator input allows at most one fractional digit. */
const ONE_DIGIT = /^\d+(\.\d)?$/
const CALENDAR_DATE = /^\d{4}-\d{2}-\d{2}$/

function utcMonthBounds(): { start: string; end: string } {
  const now = new Date()
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1))
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0))
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) }
}

function toDraft(grants: CRDGrantsSummary | null): GrantDraft {
  const bounds = utcMonthBounds()
  return {
    search: grants?.search_granted_crd ?? "",
    fetch: grants?.fetch_granted_crd ?? "",
    start: grants?.period_start ?? bounds.start,
    end: grants?.period_end ?? bounds.end,
  }
}

function amountError(value: string): string | undefined {
  if (value.trim() === "") return "Required."
  if (!ONE_DIGIT.test(value.trim())) {
    return "Use at most one decimal digit (for example 3.8)."
  }
  return undefined
}

function validateDraft(draft: GrantDraft, fetchAvailable: boolean): GrantErrors {
  const errors: GrantErrors = {}
  const search = amountError(draft.search)
  if (search) errors.search = search
  if (fetchAvailable) {
    const fetch = amountError(draft.fetch)
    if (fetch) errors.fetch = fetch
  }
  if (!CALENDAR_DATE.test(draft.start)) errors.start = "Use a calendar date."
  if (!CALENDAR_DATE.test(draft.end)) {
    errors.end = "Use a calendar date."
  } else if (!errors.start && draft.end <= draft.start) {
    errors.end = "The period end must be after the period start."
  }
  return errors
}

function fieldId(providerName: string, name: keyof GrantDraft): string {
  const slug = providerName.toLowerCase().replace(/[^a-z0-9]+/g, "-")
  return "crd-grant-" + name + "-" + slug
}

/**
 * Operator grant form: two credit-unit amounts and one period.
 *
 * The fetch field is disabled when the provider has no fetch rail, and the
 * stored fetch grant is then preserved instead of zeroed. A stale-version
 * reply from the server shows next to the form with a reload action.
 */
export function CRDGrantForm(props: CRDGrantFormProps): ReactNode {
  const { providerName, authMode, grants, fetchAvailable, saving, saveError, staleVersion } = props
  const { onSave, onReload } = props
  const [draft, setDraft] = useState<GrantDraft>(() => toDraft(grants))
  const [errors, setErrors] = useState<GrantErrors>({})

  function setField(name: keyof GrantDraft, value: string): void {
    setDraft((previous) => ({ ...previous, [name]: value }))
    setErrors((previous) => (previous[name] ? { ...previous, [name]: undefined } : previous))
  }

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (saving) return
    const found = validateDraft(draft, fetchAvailable)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    await onSave({
      auth_mode: authMode,
      version: grants?.version ?? 0,
      period_start: draft.start,
      period_end: draft.end,
      search_crd: draft.search.trim(),
      fetch_crd: fetchAvailable ? draft.fetch.trim() : (grants?.fetch_granted_crd ?? "0"),
    })
  }

  const fields: GrantField[] = [
    { name: "search", label: "Search credit units (CRD)", type: "text", disabled: saving },
    { name: "start", label: "Period start", type: "date", disabled: saving },
    { name: "end", label: "Period end", type: "date", disabled: saving },
  ]
  if (fetchAvailable) {
    fields.splice(1, 0, {
      name: "fetch",
      label: "Fetch credit units (CRD)",
      type: "text",
      disabled: saving,
    })
  }
  const stored = grants === null ? null : "Stored: search " + formatCRDAmount(grants.search_granted_crd)
    + " granted, " + formatCRDAmount(grants.search_consumed_crd) + " used, "
    + formatCRDAmount(grants.search_reserved_crd) + " reserved. Fetch "
    + formatCRDAmount(grants.fetch_granted_crd) + " granted, "
    + formatCRDAmount(grants.fetch_consumed_crd) + " used."

  return (
    <form onSubmit={(event) => void handleSubmit(event)} noValidate className="space-y-3">
      <p className="text-[12px] text-[var(--muted)]">
        Grant credit units for the {authMode} rail. One CRD is USD 0.001 of priced native use. The
        grant adds a local ceiling above the vendor balance.
      </p>
      {stored !== null && <p className="tnum text-[12px] text-[var(--muted)]">{stored}</p>}
      {!fetchAvailable && (
        <p className="text-[12px] text-[var(--muted)]">
          Fetch credit units are n/a for this provider, so the form grants search units only and
          keeps the stored fetch grant.
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {fields.map((field) => {
          const id = fieldId(providerName, field.name)
          const message = errors[field.name]
          return (
            <div key={field.name} className="space-y-1">
              <label className="block text-[12px] text-[var(--muted)]" htmlFor={id}>
                {field.label}
              </label>
              <input id={id} type={field.type} autoComplete="off" disabled={field.disabled}
                className="w-full rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1 text-[13px] text-[var(--text)]"
                inputMode={field.type === "text" ? "decimal" : undefined}
                aria-invalid={message !== undefined}
                aria-describedby={message === undefined ? undefined : id + "-error"}
                value={draft[field.name]}
                onChange={(event) => setField(field.name, event.target.value)}
              />
              {message !== undefined && (
                <p id={id + "-error"} className="text-[11px]" style={{ color: "var(--status-danger)" }}>
                  {message}
                </p>
              )}
            </div>
          )
        })}
      </div>
      {saveError !== null && (
        <p role="alert" className="rounded border border-[var(--status-danger)]/40 bg-[var(--surface)] p-2.5 text-[13px]"
          style={{ color: "var(--status-danger)" }}>
          {saveError}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="lg" className="px-3" disabled={saving}>
          {saving ? "Saving…" : "Save grant"}
        </Button>
        {staleVersion && (
          <Button type="button" variant="outline" size="lg" className="px-3" onClick={onReload}>
            Reload limits
          </Button>
        )}
      </div>
    </form>
  )
}
