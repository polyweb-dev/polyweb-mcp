import { useState } from "react"
import type { FormEvent } from "react"
import type { UsdGrantPayload, UsdGrantsSummary } from "@/domains/dashboard"
import { BudgetFields } from "@/shared/ui/BudgetFields"
import { NumericField } from "@/shared/ui/NumericField"
import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"
import { toDraft, validateDraft, grantPayloadOf, type GrantDraft, type GrantErrors } from "../model/grantForm"
import { StoredBudgetTable } from "./StoredBudgetTable"

export interface UsdGrantFormProps {
  providerName: string
  authMode: string
  grants: UsdGrantsSummary | null
  fetchAvailable: boolean
  saving: boolean
  saveError: string | null
  staleVersion: boolean
  onSave: (payload: UsdGrantPayload) => Promise<boolean>
  onClose: () => void
  onReload: () => void
}

export function UsdGrantForm(props: UsdGrantFormProps) {
  const { providerName, authMode, grants, fetchAvailable, saving, saveError, staleVersion } = props
  const [draft, setDraft] = useState<GrantDraft>(() => toDraft(grants))
  const [errors, setErrors] = useState<GrantErrors>({})
  function setField<K extends keyof GrantDraft>(name: K, value: GrantDraft[K]) {
    setDraft((previous) => ({ ...previous, [name]: value }))
    setErrors((previous) => ({ ...previous, [name]: undefined }))
  }
  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (saving) return
    const found = validateDraft(draft, fetchAvailable)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    if (await props.onSave(grantPayloadOf({ draft, authMode, grants, fetchAvailable }))) props.onClose()
  }
  const id = "provider-budget-" + providerName.toLowerCase().replace(/[^a-z0-9]+/g, "-")
  return <form onSubmit={(event) => void handleSubmit(event)} noValidate className="space-y-4">
    {grants !== null && <StoredBudgetTable grants={grants} fetchAvailable={fetchAvailable} />}
    <fieldset disabled={saving} className="space-y-4">
      <BudgetFields id={id} label="Search budget (USD)" amount={draft.search}
        onAmountChange={(value) => setField("search", value)} period={draft.period}
        onPeriodChange={(value) => setField("period", value)} error={errors.search} />
      {fetchAvailable && <NumericField id={id + "-fetch"} label="Fetch budget (USD)" prefix="$"
        min="0" step="0.000001" value={draft.fetch} onChange={(value) => setField("fetch", value)} error={errors.fetch} />}
    </fieldset>
    {saveError !== null && <p role="alert" className="fs-field-error">{saveError}</p>}
    <FormActions {...(staleVersion ? { start: <Button type="button" variant="ghost" size="form"
      onClick={props.onReload}>Reload limits</Button> } : {})}>
      <Button type="button" variant="outline" size="form" onClick={props.onClose}>Cancel</Button>
      <Button type="submit" size="form" pending={saving}>Save budget</Button>
    </FormActions>
  </form>
}
