import { calendarDateError, multiplyDecimal } from "./manualQuotaMath"
import type { CRDConversionProfile, CRDGrantPayload, CRDGrantsSummary } from "@/domains/dashboard"
import { type TavilyDisplayAdapter } from "./tavilyCredits"

export interface GrantDraft {
  search: string
  fetch: string
  start: string
  end: string
}

interface GrantField {
  name: keyof GrantDraft
  label: string
  type: "text" | "date"
  disabled: boolean
}

export type GrantErrors = Partial<Record<keyof GrantDraft, string>>
export type GrantTouched = Partial<Record<keyof GrantDraft, boolean>>

/** New USD input allows micro-dollar precision. */
const ONE_DIGIT = /^\d+(\.\d{1,6})?$/

function utcMonthBounds(): { start: string; end: string } {
  const now = new Date()
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1))
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0))
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) }
}

/** Budgets always use USD, including providers with native credit balances. */
export function conversionOf(nativeDisplay: TavilyDisplayAdapter | undefined): CRDConversionProfile | null {
  void nativeDisplay
  return null
}

/** The exact shown texts of the stored amounts, as the amount fields first render. */
export interface StoredShown {
  search: string
  fetch: string
}

/** Convert the stored ledger value into exact decimal USD. */
function shownAmount(crd: string, conversion: CRDConversionProfile | null): string {
  void conversion
  return crd === "" ? "" : multiplyDecimal(crd, "0.001") ?? ""
}

/** The shown stored amounts of the form: the exact text the fields first render. */
export function storedShownOf(grants: CRDGrantsSummary | null, conversion: CRDConversionProfile | null): StoredShown {
  return {
    search: shownAmount(grants?.search_granted_crd ?? "", conversion),
    fetch: shownAmount(grants?.fetch_granted_crd ?? "", conversion),
  }
}

export function toDraft(grants: CRDGrantsSummary | null, conversion: CRDConversionProfile | null): GrantDraft {
  const bounds = utcMonthBounds()
  const shown = storedShownOf(grants, conversion)
  return {
    search: shown.search,
    fetch: shown.fetch,
    start: grants?.period_start ?? bounds.start,
    end: grants?.period_end ?? bounds.end,
  }
}

/** Precision validation applies to edited amounts only. */
function amountError(value: string, changed: boolean): string | undefined {
  if (value.trim() === "") return "Enter an amount"
  if (!changed) return undefined
  if (!ONE_DIGIT.test(value.trim())) {
    return "Use up to six decimal places"
  }
  return undefined
}

/**
 * Whether one amount field counts as changed: touched and not the exact shown
 * amount of the stored CRD value. An edit that restores the exact text the
 * form rendered first reads as unchanged, so the submit keeps the stored CRD
 * verbatim; edited USD supports six decimal places.
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

export function validateDraft(
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
  if (calendarDateError(draft.start)) errors.start = "Enter a valid date"
  if (calendarDateError(draft.end)) {
    errors.end = "Enter a valid date"
  } else if (!errors.start && draft.end <= draft.start) {
    errors.end = "The period end must be after the period start"
  }
  return errors
}


export function fieldId(providerName: string, name: keyof GrantDraft): string {
  const slug = providerName.toLowerCase().replace(/[^a-z0-9]+/g, "-")
  return "crd-grant-" + name + "-" + slug
}

/** Both operation budgets use the same USD unit. */
function amountLabelOf(operation: "search" | "fetch", conversion: CRDConversionProfile | null): string {
  const name = operation === "fetch" ? "Fetch budget" : "Search budget"
  void conversion
  return name + " (USD)"
}

/** The field set of one draft: the fetch amount field exists only then. */
export function fieldsOf(fetchAvailable: boolean, conversion: CRDConversionProfile | null, saving: boolean): GrantField[] {
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
export interface Submission {
  draft: GrantDraft
  touched: GrantTouched
  conversion: CRDConversionProfile | null
  fetchAvailable: boolean
  authMode: string
  grants: CRDGrantsSummary | null
  /** The exact shown texts of the stored amounts, as the fields first render. */
  storedShown: StoredShown
}

/** Convert edited USD to the internal view model until the API boundary. */
function submitAmountOf(name: "search" | "fetch", submission: Submission): string {
  const stored = name === "search"
    ? submission.grants?.search_granted_crd ?? ""
    : submission.grants?.fetch_granted_crd ?? "0"
  if (!changedAmount(name, submission.draft, submission.touched, submission.storedShown)) {
    return stored
  }
  const shown = submission.draft[name].trim()
  return multiplyDecimal(shown, "1000") ?? shown
}

/** The save payload of one validated draft. */
export function grantPayloadOf(submission: Submission): CRDGrantPayload {
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
