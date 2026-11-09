import { useState } from "react"
import type { ReactNode } from "react"
import type { BackendManualQuotaPayload } from "@/domains/dashboard/api/manualQuotaWire"
import { subtractDecimal, type ManualAmountMode } from "../model/manualQuotaMath"
import type { BalancePrefill } from "../model/providerInfo"
import type { CreditMode } from "../model/quotaLabels"
import { useQuotaForm, type ManualQuotaDefaults } from "../model/useQuotaForm"
import { ManualQuotaActions } from "./ManualQuotaActions"
import { ManualQuotaFields } from "./ManualQuotaFields"

export interface ManualEntryFormProps {
  providerId: string
  noun: string
  placeholders: { allowance: string; used: string }
  /** The saved entry of this provider; a null value starts a new entry. */
  defaults: ManualQuotaDefaults | null
  /** The observed balance of this provider, which starts a new entry as an estimate. */
  observed: BalancePrefill | null
  creditMode: CreditMode
  amountMode: ManualAmountMode
  /** The provider field of the shell, shown first. */
  providerField: ReactNode
  onSave: (payload: BackendManualQuotaPayload, providerId?: string) => Promise<unknown>
  onDelete?: () => Promise<unknown>
  onClose: () => void
}

/**
 * The starting fields of one estimate: the observed allowance and the observed
 * remaining amount. The hook turns the second amount into the field it shows.
 */
function prefillDefaults(prefill: BalancePrefill | null): ManualQuotaDefaults | null {
  if (prefill === null) return null
  const used = subtractDecimal(prefill.allowance, prefill.remaining)
  if (used === null) return null
  return { billingStart: "", billingEnd: "", allowance: prefill.allowance, used }
}

/**
 * The fields, the preview, and the actions of one manual entry.
 *
 * A saved entry of the provider wins on open. A provider without a saved entry
 * starts from its observed balance, and the form states that estimate. The
 * live values therefore never overwrite a saved entry.
 */
export function ManualEntryForm(props: ManualEntryFormProps): ReactNode {
  const {
    providerId,
    noun,
    placeholders,
    defaults,
    observed,
    creditMode,
    amountMode,
    providerField,
    onSave,
    onDelete,
    onClose,
  } = props
  const [mode, setMode] = useState<CreditMode>(noun === "USD" ? "paid" : creditMode)
  const entryAmountMode = mode === "both" ? amountMode : "balance"
  const saved = defaults !== null && defaults.allowance !== "" ? defaults : null
  const estimate = saved === null ? prefillDefaults(observed) : null
  const form = useQuotaForm(
    saved ?? estimate,
    {
      onSave: (payload) => onSave(payload, providerId),
      ...(onDelete !== undefined ? { onDelete } : {}),
      onClose,
    },
    entryAmountMode
  )

  return (
    <form onSubmit={(event) => void form.handleSubmit(event)} noValidate>
      <ManualQuotaFields
        providerId={providerId}
        noun={noun}
        placeholders={placeholders}
        fields={form.fields}
        fieldErrors={form.fieldErrors}
        pending={form.pending}
        mode={mode}
        onModeChange={setMode}
        onChange={form.setField}
        providerField={providerField}
        amountMode={entryAmountMode}
        preview={form.preview}
      />
      {form.saveError && (
        <p
          role="alert"
          data-testid="manual-quota-error"
          className="mt-3 p-2.5 rounded border border-[var(--status-danger)]/40 bg-[var(--surface)] text-[13px]"
          style={{ color: "var(--status-danger)" }}
        >
          {form.saveError}
        </p>
      )}
      <ManualQuotaActions
        isEditing={saved !== null}
        canDelete={Boolean(onDelete)}
        pending={form.pending}
        saving={form.saving}
        deleting={form.deleting}
        onCancel={onClose}
        onDelete={() => void form.handleDelete()}
      />
    </form>
  )
}
