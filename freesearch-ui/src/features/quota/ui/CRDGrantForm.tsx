import { useState } from "react"
import type { FormEvent, ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"
import { TextField } from "@/shared/ui/TextField"
import type { CRDGrantPayload, CRDGrantsSummary } from "@/domains/dashboard"
import type { TavilyDisplayAdapter } from "../model/tavilyCredits"
import { conversionOf, storedShownOf, toDraft, validateDraft, fieldsOf, fieldId, grantPayloadOf, type GrantDraft, type GrantErrors, type GrantTouched, type StoredShown, type Submission } from "../model/grantForm"
import { StoredBudgetTable } from "./StoredBudgetTable"
import { QuotaDateField } from "./QuotaDateField"
import { SPEND_CAP } from "../model/quotaLabels"

export interface CRDGrantFormProps {
  providerName: string
  authMode: string
  referenceUSDPerCRD?: string
  grants: CRDGrantsSummary | null
  fetchAvailable: boolean
  saving: boolean
  saveError: string | null
  staleVersion: boolean
  /**
   * Legacy native display inputs do not change the USD budget unit.
   */
  nativeDisplay?: TavilyDisplayAdapter
  onSave: (payload: CRDGrantPayload) => Promise<boolean>
  onClose: () => void
  onReload: () => void
}

/** USD budget form. Unchanged drafts preserve exact persisted ledger amounts. */
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
    <form onSubmit={(event) => void handleSubmit(event)} noValidate className="space-y-4">
      {grants !== null && <StoredBudgetTable grants={grants} fetchAvailable={fetchAvailable} conversion={conversion} />}
      <div className="grid grid-cols-1 gap-4">
        {fields.map((field) => field.type === "date" ? (
          <QuotaDateField key={field.name} id={fieldId(providerName, field.name)} label={field.label}
            value={draft[field.name]} error={errors[field.name]} disabled={saving}
            onChange={(value) => setField(field.name, value)} />
        ) : (
          <TextField key={field.name} id={fieldId(providerName, field.name)} label={field.label}
            type="text" autoComplete="off" disabled={field.disabled} value={draft[field.name]}
            error={errors[field.name] ?? null} onChange={(value) => setField(field.name, value)} />
        ))}
      </div>
      {saveError !== null && (
        <p role="alert" className="fs-field-error">
          {saveError}
        </p>
      )}
      <FormActions
        {...(staleVersion
          ? {
              start: (
                <Button type="button" variant="ghost" size="form" onClick={onReload}>
                  Reload limits
                </Button>
              ),
            }
          : {})}
      >
        <Button type="button" variant="outline" size="form" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" size="form" disabled={saving}>
          {saving ? "Saving…" : "Save " + SPEND_CAP.toLowerCase()}
        </Button>
      </FormActions>
    </form>
  )
}
