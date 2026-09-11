import { useState } from "react"
import type { FormEvent } from "react"
import { ApiError } from "@/shared/api/http"
import type { BackendManualQuotaPayload } from "@/services/api/backendTypes"
import {
  remainingPercent1dp,
  validateManualQuotaFields,
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

function toFields(defaults: ManualQuotaDefaults | null | undefined): ManualQuotaFields {
  return {
    billingStart: defaults?.billingStart ?? "",
    billingEnd: defaults?.billingEnd ?? "",
    allowance: defaults?.allowance ?? "",
    used: defaults?.used ?? "",
  }
}

function saveErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail || "Unable to save Manual Entry"
  if (error instanceof Error && error.message) return error.message
  return "Unable to save Manual Entry"
}

/** Field state, validation, preview, and save/delete for the manual form. */
export function useQuotaForm(
  initial: ManualQuotaDefaults | null | undefined,
  callbacks: QuotaFormCallbacks
): QuotaForm {
  const { onSave, onDelete, onClose } = callbacks
  const [fields, setFields] = useState<ManualQuotaFields>(() => toFields(initial))
  const [fieldErrors, setFieldErrors] = useState<ManualQuotaFieldErrors>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const pending = saving || deleting
  const preview = remainingPercent1dp(fields.allowance, fields.used)

  function setField(name: keyof ManualQuotaFields, value: string): void {
    setFields((previous) => ({ ...previous, [name]: value }))
    setFieldErrors((previous) =>
      previous[name] ? { ...previous, [name]: undefined } : previous
    )
  }

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (pending) return
    const errors = validateManualQuotaFields(fields)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return
    setSaving(true)
    try {
      await onSave({
        billing_start: fields.billingStart,
        billing_end: fields.billingEnd,
        allowance: fields.allowance.trim(),
        current_usage: fields.used.trim(),
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
