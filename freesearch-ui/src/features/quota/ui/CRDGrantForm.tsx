import { useState } from "react"
import type { FormEvent, ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import type { CRDConversionProfile, CRDGrantPayload, CRDGrantsSummary } from "@/domains/dashboard"
import { formatCRDAmount } from "../model/crdDisplay"
import {
  formatCreditAmount,
  tavilyCreditsToCRD,
  tavilyCRDToCredits,
  type TavilyDisplayAdapter,
} from "../model/tavilyCredits"
import { SPEND_CAP } from "../model/quotaLabels"

export interface CRDGrantFormProps {
  providerName: string
  authMode: string
  grants: CRDGrantsSummary | null
  fetchAvailable: boolean
  saving: boolean
  saveError: string | null
  staleVersion: boolean
  /**
   * Optional native display inputs of one rail. With them and a known price
   * profile, the fields state native Credits and convert the typed amount back
   * to CRD at submit time. Without them the form keeps its CRD behavior.
   */
  nativeDisplay?: TavilyDisplayAdapter
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

/** The conversion profile of the form: absent inputs or prices keep CRD shown. */
function conversionOf(nativeDisplay: TavilyDisplayAdapter | undefined): CRDConversionProfile | null {
  if (nativeDisplay === undefined) return null
  return nativeDisplay.profile
}

/** The exact shown texts of the stored amounts, as the amount fields first render. */
interface StoredShown {
  search: string
  fetch: string
}

/** The shown amount of one stored CRD value: native Credits when convertible. */
function shownAmount(crd: string, conversion: CRDConversionProfile | null): string {
  if (crd === "" || conversion === null) return crd
  const credits = tavilyCRDToCredits(crd, conversion)
  return credits === null ? crd : credits
}

/** The shown stored amounts of the form: the exact text the fields first render. */
function storedShownOf(grants: CRDGrantsSummary | null, conversion: CRDConversionProfile | null): StoredShown {
  return {
    search: shownAmount(grants?.search_granted_crd ?? "", conversion),
    fetch: shownAmount(grants?.fetch_granted_crd ?? "", conversion),
  }
}

function toDraft(grants: CRDGrantsSummary | null, conversion: CRDConversionProfile | null): GrantDraft {
  const bounds = utcMonthBounds()
  const shown = storedShownOf(grants, conversion)
  return {
    search: shown.search,
    fetch: shown.fetch,
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

/**
 * Whether one amount field counts as changed: touched and not the exact shown
 * amount of the stored CRD value. An edit that restores the exact text the
 * form rendered first reads as unchanged, so the submit keeps the stored CRD
 * verbatim; every other touched text keeps the one-digit rule.
 */
function changedAmount(
  name: "search" | "fetch",
  draft: GrantDraft,
  touched: GrantTouched,
  storedShown: StoredShown,
): boolean {
  if (touched[name] !== true) return false
  return draft[name].trim() !== storedShown[name]
}

function validateDraft(
  draft: GrantDraft,
  fetchAvailable: boolean,
  touched: GrantTouched,
  storedShown: StoredShown,
): GrantErrors {
  const errors: GrantErrors = {}
  const search = amountError(draft.search, changedAmount("search", draft, touched, storedShown))
  if (search) errors.search = search
  if (fetchAvailable) {
    const fetch = amountError(draft.fetch, changedAmount("fetch", draft, touched, storedShown))
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

/** The shown text of one stored amount: Credits under a profile, CRD otherwise. */
function storedAmountText(crd: string, conversion: CRDConversionProfile | null): string {
  if (conversion === null) return formatCRDAmount(crd)
  const credits = tavilyCRDToCredits(crd, conversion)
  return credits === null ? formatCRDAmount(crd) : formatCreditAmount(credits)
}

/** Stored facts of the reported operations only; an absent rail stays absent. */
function storedText(
  grants: CRDGrantsSummary,
  fetchAvailable: boolean,
  conversion: CRDConversionProfile | null,
): string {
  const search =
    "Stored " +
    SPEND_CAP.toLowerCase() +
    ": search " +
    storedAmountText(grants.search_granted_crd, conversion) +
    " set, " +
    storedAmountText(grants.search_consumed_crd, conversion) +
    " used, " +
    storedAmountText(grants.search_reserved_crd, conversion) +
    " reserved."
  if (!fetchAvailable) return search
  return (
    search +
    " Fetch " +
    storedAmountText(grants.fetch_granted_crd, conversion) +
    " set, " +
    storedAmountText(grants.fetch_consumed_crd, conversion) +
    " used."
  )
}

function fieldId(providerName: string, name: keyof GrantDraft): string {
  const slug = providerName.toLowerCase().replace(/[^a-z0-9]+/g, "-")
  return "crd-grant-" + name + "-" + slug
}

/** The shown label of one amount field: native Credits under a profile, CRD otherwise. */
function amountLabelOf(operation: "search" | "fetch", conversion: CRDConversionProfile | null): string {
  if (conversion === null) return operation.charAt(0).toUpperCase() + operation.slice(1) + " credit units (CRD)"
  return operation === "fetch" ? "Fetch Credits" : "Search Credits"
}

/** The field set of one draft: the fetch amount field exists only then. */
function fieldsOf(fetchAvailable: boolean, conversion: CRDConversionProfile | null, saving: boolean): GrantField[] {
  const fields: GrantField[] = [
    { name: "search", label: amountLabelOf("search", conversion), type: "text", disabled: saving },
    { name: "start", label: "Period start", type: "date", disabled: saving },
    { name: "end", label: "Period end", type: "date", disabled: saving },
  ]
  if (fetchAvailable) {
    fields.splice(1, 0, {
      name: "fetch",
      label: amountLabelOf("fetch", conversion),
      type: "text",
      disabled: saving,
    })
  }
  return fields
}

/** The draft and its native conversion state at submit time. */
interface Submission {
  draft: GrantDraft
  touched: GrantTouched
  conversion: CRDConversionProfile | null
  fetchAvailable: boolean
  authMode: string
  grants: CRDGrantsSummary | null
  /** The exact shown texts of the stored amounts, as the fields first render. */
  storedShown: StoredShown
}

/** The outgoing CRD amount of one field: typed Credits convert back at submit. */
function submitAmountOf(name: "search" | "fetch", submission: Submission): string {
  const stored = name === "search"
    ? submission.grants?.search_granted_crd ?? ""
    : submission.grants?.fetch_granted_crd ?? "0"
  if (!changedAmount(name, submission.draft, submission.touched, submission.storedShown)) {
    return stored
  }
  const shown = submission.draft[name].trim()
  if (submission.conversion === null) return shown
  const crd = tavilyCreditsToCRD(shown, submission.conversion)
  return crd === null ? shown : crd
}

/** The save payload of one validated draft. */
function grantPayloadOf(submission: Submission): CRDGrantPayload {
  return {
    auth_mode: submission.authMode,
    version: submission.grants?.version ?? 0,
    period_start: submission.draft.start,
    period_end: submission.draft.end,
    search_crd: submitAmountOf("search", submission),
    fetch_crd: submission.fetchAvailable
      ? submitAmountOf("fetch", submission)
      : (submission.grants?.fetch_granted_crd ?? "0"),
  }
}

/**
 * Operator spend cap form: one credit-unit amount per supported operation and
 * one period. The fetch field exists only for a fetch rail, and the stored fetch
 * cap is then preserved in the request. A save that fails keeps the draft, and
 * the modal closes only after a successful save.
 *
 * With native display inputs and a known price profile the fields state native
 * Credits: the draft keeps the shown amount, an untouched field submits the
 * stored CRD value verbatim, and a typed amount converts back to CRD at submit
 * time. A touched field that restores the exact shown text of the stored amount
 * submits the stored CRD verbatim as well. An unknown price profile keeps the
 * whole form on CRD.
 */
export function CRDGrantForm(props: CRDGrantFormProps): ReactNode {
  const { providerName, authMode, grants, fetchAvailable, saving, saveError, staleVersion } = props
  const { onSave, onClose, onReload, nativeDisplay } = props
  const conversion = conversionOf(nativeDisplay)
  const [draft, setDraft] = useState<GrantDraft>(() => toDraft(grants, conversion))
  // The shown stored amounts of the seeded draft stay mounted beside it: a
  // touched edit that restores this exact text submits the stored CRD
  // verbatim, as the unchanged fields do.
  const [storedShown] = useState<StoredShown>(() => storedShownOf(grants, conversion))
  const [errors, setErrors] = useState<GrantErrors>({})
  const [touched, setTouched] = useState<GrantTouched>({})
  const fields = fieldsOf(fetchAvailable, conversion, saving)
  const stored = grants === null ? null : storedText(grants, fetchAvailable, conversion)

  function setField(name: keyof GrantDraft, value: string): void {
    setDraft((previous) => ({ ...previous, [name]: value }))
    setTouched((previous) => ({ ...previous, [name]: true }))
    setErrors((previous) => (previous[name] ? { ...previous, [name]: undefined } : previous))
  }

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (saving) return
    const submission: Submission = {
      draft,
      touched,
      conversion,
      fetchAvailable,
      authMode,
      grants,
      storedShown,
    }
    const found = validateDraft(draft, fetchAvailable, touched, storedShown)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    const saved = await onSave(grantPayloadOf(submission))
    if (saved) onClose()
  }

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
