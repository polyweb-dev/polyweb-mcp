import { useState } from "react"
import type { FormEvent, ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import type { CRDGrantPayload, CRDGrantsSummary } from "@/domains/dashboard"
import { formatCRDAmount } from "../model/crdDisplay"
import { SPEND_CAP } from "../model/quotaLabels"

export interface CRDGrantFormProps {
  providerName: string
  authMode: string
  grants: CRDGrantsSummary | null
  fetchAvailable: boolean
  saving: boolean
  saveError: string | null
  staleVersion: boolean
  onSave: (payload: CRDGrantPayload) => Promise<boolean>
  onClose: () => void
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
type GrantTouched = Partial<Record<keyof GrantDraft, boolean>>

/** New operator input allows at most one fractional digit. */
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

/** The one-digit rule applies to new input only, never to a stored server amount. */
function amountError(value: string, changed: boolean): string | undefined {
  if (value.trim() === "") return "Required."
  if (!changed) return undefined
  if (!ONE_DIGIT.test(value.trim())) {
    return "Use at most one decimal digit (for example 3.8)."
  }
  return undefined
}

function validateDraft(
  draft: GrantDraft,
  fetchAvailable: boolean,
  touched: GrantTouched,
): GrantErrors {
  const errors: GrantErrors = {}
  const search = amountError(draft.search, touched.search === true)
  if (search) errors.search = search
  if (fetchAvailable) {
    const fetch = amountError(draft.fetch, touched.fetch === true)
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

/** Stored facts of the reported operations only; an absent rail stays absent. */
function storedText(grants: CRDGrantsSummary, fetchAvailable: boolean): string {
  const search =
    "Stored " +
    SPEND_CAP.toLowerCase() +
    ": search " +
    formatCRDAmount(grants.search_granted_crd) +
    " set, " +
    formatCRDAmount(grants.search_consumed_crd) +
    " used, " +
    formatCRDAmount(grants.search_reserved_crd) +
    " reserved."
  if (!fetchAvailable) return search
  return (
    search +
    " Fetch " +
    formatCRDAmount(grants.fetch_granted_crd) +
    " set, " +
    formatCRDAmount(grants.fetch_consumed_crd) +
    " used."
  )
}

function fieldId(providerName: string, name: keyof GrantDraft): string {
  const slug = providerName.toLowerCase().replace(/[^a-z0-9]+/g, "-")
  return "crd-grant-" + name + "-" + slug
}

/**
 * Operator spend cap form: one credit-unit amount per supported operation and
 * one period. The fetch field exists only for a fetch rail, and the stored fetch
 * cap is then preserved in the request. A save that fails keeps the draft, and
 * the modal closes only after a successful save.
 */
export function CRDGrantForm(props: CRDGrantFormProps): ReactNode {
  const { providerName, authMode, grants, fetchAvailable, saving, saveError, staleVersion } = props
  const { onSave, onClose, onReload } = props
  const [draft, setDraft] = useState<GrantDraft>(() => toDraft(grants))
  const [errors, setErrors] = useState<GrantErrors>({})
  const [touched, setTouched] = useState<GrantTouched>({})

  function setField(name: keyof GrantDraft, value: string): void {
    setDraft((previous) => ({ ...previous, [name]: value }))
    setTouched((previous) => ({ ...previous, [name]: true }))
    setErrors((previous) => (previous[name] ? { ...previous, [name]: undefined } : previous))
  }

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (saving) return
    const found = validateDraft(draft, fetchAvailable, touched)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    const saved = await onSave({
      auth_mode: authMode,
      version: grants?.version ?? 0,
      period_start: draft.start,
      period_end: draft.end,
      search_crd: draft.search.trim(),
      fetch_crd: fetchAvailable ? draft.fetch.trim() : (grants?.fetch_granted_crd ?? "0"),
    })
    if (saved) onClose()
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
  const stored = grants === null ? null : storedText(grants, fetchAvailable)

  return (
    <form onSubmit={(event) => void handleSubmit(event)} noValidate className="space-y-3">
      {stored !== null && <p className="tnum text-[12px] text-[var(--muted)]">{stored}</p>}
      <div className="grid grid-cols-1 gap-3">
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
          {saving ? "Saving…" : "Save " + SPEND_CAP.toLowerCase()}
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
