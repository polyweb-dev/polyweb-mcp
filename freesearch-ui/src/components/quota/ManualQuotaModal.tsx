import React, { useState } from "react"
import { Modal } from "@/components/common/Modal"
import { Button } from "@/components/ui/button"
import { unitLabel } from "@/services/api/mappers"
import { ApiError } from "@/shared/api/http"
import type { BackendManualQuotaPayload } from "@/services/api/backendTypes"
import type { UnitKind } from "@/types/freesearch"
import {
  formatPercent1dp,
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

export interface ManualQuotaModalProps {
  open: boolean
  providerId: string
  providerName: string
  unitKind: UnitKind | null
  displayUnit?: string | null
  defaults?: ManualQuotaDefaults | null
  onClose: () => void
  onSave: (payload: BackendManualQuotaPayload) => Promise<unknown>
  onDelete?: () => Promise<unknown>
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

function placeholdersFor(unitKind: UnitKind | null): { allowance: string; used: string } {
  if (unitKind === "USD") return { allowance: "5.00", used: "0.88" }
  if (unitKind === "REQUEST") return { allowance: "1000", used: "120" }
  if (unitKind === "CREDIT") return { allowance: "100000", used: "12000" }
  return { allowance: "100", used: "12" }
}

interface QuotaForm {
  fields: ManualQuotaFields
  fieldErrors: ManualQuotaFieldErrors
  saveError: string | null
  saving: boolean
  deleting: boolean
  pending: boolean
  preview: number | null
  setField: (name: keyof ManualQuotaFields, value: string) => void
  handleSubmit: (event: React.FormEvent) => Promise<void>
  handleDelete: () => Promise<void>
}

interface QuotaFormOptions {
  initial: ManualQuotaDefaults | null | undefined
  onSave: ManualQuotaModalProps["onSave"]
  onDelete: ManualQuotaModalProps["onDelete"]
  onClose: () => void
}

function useQuotaForm({ initial, onSave, onDelete, onClose }: QuotaFormOptions): QuotaForm {
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

  async function handleSubmit(event: React.FormEvent): Promise<void> {
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

/**
 * Reusable manual billing entry (Brave first; Exa/Parallel reuse it with
 * USD units). Mount it only while open (or key it per session): field state
 * initialises from `defaults` at mount. The vendor throttle headline is
 * never rewritten here — the saved window renders as an estimated overlay.
 */
export const ManualQuotaModal: React.FC<ManualQuotaModalProps> = (props) => {
  const {
    open,
    providerId,
    providerName,
    unitKind,
    displayUnit = null,
    defaults = null,
    onClose,
    onSave,
    onDelete,
  } = props
  const rawNoun = unitLabel(unitKind, displayUnit)
  // Presentation fallback only; branching logic still uses unitKind.
  const noun = rawNoun === "legacy" ? "units" : rawNoun
  const placeholders = placeholdersFor(unitKind)
  const isEditing = Boolean(defaults?.allowance)
  const form = useQuotaForm({ initial: defaults, onSave, onDelete, onClose })

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      maxWidth="sm"
      title={`${isEditing ? "Update usage" : "Set budget"} — ${providerName}`}
      subtitle="Manual billing window. Estimated locally; not a vendor balance."
    >
      <form onSubmit={(event) => void form.handleSubmit(event)} noValidate>
        <QuotaFieldsGrid
          providerId={providerId}
          noun={noun}
          placeholders={placeholders}
          fields={form.fields}
          fieldErrors={form.fieldErrors}
          pending={form.pending}
          onChange={form.setField}
        />
        <p
          data-testid="manual-quota-preview"
          aria-live="polite"
          className="mt-3 text-[12px] text-[var(--muted)] tnum"
        >
          {form.preview === null
            ? "Enter an allowance and usage to preview the estimated percentage."
            : `Estimated ${formatPercent1dp(form.preview)}% remaining`}
        </p>
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
        <QuotaModalActions
          isEditing={isEditing}
          canDelete={Boolean(onDelete)}
          pending={form.pending}
          saving={form.saving}
          deleting={form.deleting}
          onCancel={onClose}
          onDelete={() => void form.handleDelete()}
        />
      </form>
    </Modal>
  )
}

interface QuotaFieldsGridProps {
  providerId: string
  noun: string
  placeholders: { allowance: string; used: string }
  fields: ManualQuotaFields
  fieldErrors: ManualQuotaFieldErrors
  pending: boolean
  onChange: (name: keyof ManualQuotaFields, value: string) => void
}

const QuotaFieldsGrid: React.FC<QuotaFieldsGridProps> = ({
  providerId,
  noun,
  placeholders,
  fields,
  fieldErrors,
  pending,
  onChange,
}) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
    <Field
      id={`manual-quota-start-${providerId}`}
      testId="manual-quota-start"
      label="Billing start"
      error={fieldErrors.billingStart}
      disabled={pending}
      render={(inputProps) => (
        <input
          type="date"
          value={fields.billingStart}
          onChange={(event) => onChange("billingStart", event.target.value)}
          {...inputProps}
        />
      )}
    />
    <Field
      id={`manual-quota-end-${providerId}`}
      testId="manual-quota-end"
      label="Billing end"
      error={fieldErrors.billingEnd}
      disabled={pending}
      render={(inputProps) => (
        <input
          type="date"
          value={fields.billingEnd}
          onChange={(event) => onChange("billingEnd", event.target.value)}
          {...inputProps}
        />
      )}
    />
    <Field
      id={`manual-quota-allowance-${providerId}`}
      testId="manual-quota-allowance"
      label={`Allowance (${noun})`}
      error={fieldErrors.allowance}
      disabled={pending}
      render={(inputProps) => (
        <input
          type="text"
          inputMode="decimal"
          autoComplete="off"
          placeholder={placeholders.allowance}
          value={fields.allowance}
          onChange={(event) => onChange("allowance", event.target.value)}
          {...inputProps}
        />
      )}
    />
    <Field
      id={`manual-quota-usage-${providerId}`}
      testId="manual-quota-usage"
      label={`Current usage (${noun})`}
      error={fieldErrors.used}
      disabled={pending}
      render={(inputProps) => (
        <input
          type="text"
          inputMode="decimal"
          autoComplete="off"
          placeholder={placeholders.used}
          value={fields.used}
          onChange={(event) => onChange("used", event.target.value)}
          {...inputProps}
        />
      )}
    />
  </div>
)

const QuotaModalActions: React.FC<{
  isEditing: boolean
  canDelete: boolean
  pending: boolean
  saving: boolean
  deleting: boolean
  onCancel: () => void
  onDelete: () => void
}> = ({ isEditing, canDelete, pending, saving, deleting, onCancel, onDelete }) => (
  <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
    <span>
      {isEditing && canDelete && (
        <Button
          type="button"
          variant="outline"
          size="lg" className="px-3"
          data-testid="manual-quota-clear"
          disabled={pending}
          onClick={onDelete}
        >
          {deleting ? "Clearing…" : "Clear entry"}
        </Button>
      )}
    </span>
    <span className="flex items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="lg" className="px-3"
        data-testid="manual-quota-cancel"
        disabled={pending}
        onClick={onCancel}
      >
        Cancel
      </Button>
      <Button type="submit" size="lg" className="px-3" data-testid="manual-quota-save" disabled={pending}>
        {saving ? "Saving…" : isEditing ? "Save usage" : "Save budget"}
      </Button>
    </span>
  </div>
)

interface FieldRenderProps {
  id: string
  "aria-invalid": boolean
  "aria-describedby": string | undefined
  disabled: boolean
  className: string
  "data-testid": string
}

const Field: React.FC<{
  id: string
  testId: string
  label: string
  error: string | undefined
  disabled: boolean
  render: (inputProps: FieldRenderProps) => React.ReactNode
}> = ({ id, testId, label, error, disabled, render }) => {
  const errorId = error ? `${id}-error` : undefined
  return (
    <div>
      <label htmlFor={id} className="block text-[12px] text-[var(--muted)] mb-1">
        {label}
      </label>
      {render({
        id,
        "aria-invalid": Boolean(error),
        "aria-describedby": errorId,
        disabled,
        className:
          "w-full rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1.5 text-[13px] text-[var(--text)] tnum outline-none focus-visible:border-[var(--signal)]",
        "data-testid": testId,
      })}
      {error && (
        <p
          id={errorId}
          data-testid={`${testId}-error`}
          className="mt-1 text-[12px]"
          style={{ color: "var(--status-danger)" }}
        >
          {error}
        </p>
      )}
    </div>
  )
}
