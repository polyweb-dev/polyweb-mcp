import { useState } from "react"
import type { FormEvent } from "react"
import { ApiError } from "@/shared/api/http"
import type { BackendManualQuotaPayload } from "@/domains/dashboard/api/manualQuotaWire"
import {
  remainingPercent1dp,
  subtractDecimal,
  validateManualQuotaFields,
  type ManualAmountMode,
  type ManualQuotaFieldErrors,
  type ManualQuotaFields,
} from "./manualQuotaMath"
export interface ManualQuotaDefaults {
  billingStart: string
  billingEnd: string
  allowance: string
  used: string
}

export interface QuotaForm {
  fields: ManualQuotaFields
  fieldErrors: ManualQuotaFieldErrors
  saveError: string | null
  saving: boolean
  deleting: boolean
  pending: boolean
  preview: number | null
  setField: (name: keyof ManualQuotaFields, value: string) => void
  handleSubmit: (event: FormEvent) => Promise<void>
  handleDelete: () => Promise<void>
}

export interface QuotaFormCallbacks {
  onSave: (payload: BackendManualQuotaPayload) => Promise<unknown>
  onDelete?: () => Promise<unknown>
  onClose: () => void
}

function toFields(
  defaults: ManualQuotaDefaults | null | undefined,
  amountMode: ManualAmountMode
): ManualQuotaFields {
  const allowance = defaults?.allowance ?? ""
  const used = defaults?.used ?? ""
  // A saved current usage becomes the displayed remaining balance.
  const shown = amountMode === "balance" ? (subtractDecimal(allowance, used) ?? used) : used
  return {
    billingStart: defaults?.billingStart ?? "",
    billingEnd: defaults?.billingEnd ?? "",
    allowance,
    used: shown,
  }
}

/** The current usage the native-anchor endpoint receives. */
function usageOf(fields: ManualQuotaFields, amountMode: ManualAmountMode): string {
  if (amountMode !== "balance") return fields.used.trim()
  return subtractDecimal(fields.allowance, fields.used) ?? fields.used.trim()
}

function saveErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail || "Unable to save Manual Entry"
  if (error instanceof Error && error.message) return error.message
  return "Unable to save Manual Entry"
}

/**
 * Field state, validation, preview, and save/delete for the manual form.
 * In balance mode the amount field holds the remaining balance, so the hook
 * translates it to the current usage the endpoint expects.
 */
export function useQuotaForm(
  initial: ManualQuotaDefaults | null | undefined,
  callbacks: QuotaFormCallbacks,
  amountMode: ManualAmountMode = "usage"
): QuotaForm {
  const { onSave, onDelete, onClose } = callbacks
  const [fields, setFields] = useState<ManualQuotaFields>(() => toFields(initial, amountMode))
  const [fieldErrors, setFieldErrors] = useState<ManualQuotaFieldErrors>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const pending = saving || deleting
  const preview = remainingPercent1dp(fields.allowance, usageOf(fields, amountMode))

  function setField(name: keyof ManualQuotaFields, value: string): void {
    setFields((previous) => ({ ...previous, [name]: value }))
    setFieldErrors((previous) =>
      previous[name] ? { ...previous, [name]: undefined } : previous
    )
  }

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (pending) return
    const errors = validateManualQuotaFields(fields, amountMode)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return
    setSaving(true)
    try {
      await onSave({
        billing_start: fields.billingStart,
        billing_end: fields.billingEnd,
        allowance: fields.allowance.trim(),
        current_usage: usageOf(fields, amountMode),
      })
      onClose()
    } catch (error) {
      setSaveError(saveErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(): Promise<void> {
    if (!onDelete || pending) return
    setDeleting(true)
    try {
      await onDelete()
      onClose()
    } catch (error) {
      setSaveError(saveErrorMessage(error))
    } finally {
      setDeleting(false)
    }
  }

  return {
    fields,
    fieldErrors,
    saveError,
    saving,
    deleting,
    pending,
    preview,
    setField,
    handleSubmit,
    handleDelete,
  }
}
