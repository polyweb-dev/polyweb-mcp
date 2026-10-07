import type { ReactNode } from "react"
import type { ManualAmountMode, ManualQuotaFieldErrors, ManualQuotaFields } from "../model/manualQuotaMath"
import {
  CREDIT_MODE_FIELD,
  CREDIT_MODE_LABEL,
  CREDIT_MODES,
  type CreditMode,
} from "../model/quotaLabels"
import { ManualQuotaField } from "./ManualQuotaField"

export interface ManualQuotaFieldsProps {
  providerId: string
  noun: string
  placeholders: { allowance: string; used: string }
  fields: ManualQuotaFields
  fieldErrors: ManualQuotaFieldErrors
  pending: boolean
  /** The credit tier of this entry. The API carries no tier field, so it shows only. */
  mode: CreditMode
  onModeChange: (mode: CreditMode) => void
  onChange: (name: keyof ManualQuotaFields, value: string) => void
  /** The provider field of the shell, shown first. */
  providerField?: ReactNode
  /** `balance` labels the second amount as the remaining balance. */
  amountMode?: ManualAmountMode
}

/** The mode combo of one manual entry. */
function modeField(
  providerId: string,
  mode: CreditMode,
  pending: boolean,
  onModeChange: (mode: CreditMode) => void,
) {
  return (
    <ManualQuotaField
      id={"manual-quota-mode-" + providerId}
      testId="manual-quota-mode"
      label={CREDIT_MODE_FIELD}
      error={undefined}
      disabled={pending}
      render={(inputProps) => (
        <select
          value={mode}
          onChange={(event) => onModeChange(event.target.value as CreditMode)}
          {...inputProps}
        >
          {CREDIT_MODES.map((option) => (
            <option key={option} value={option}>
              {CREDIT_MODE_LABEL[option]}
            </option>
          ))}
        </select>
      )}
    />
  )
}

/** Billing window form section: the provider, the credit mode, the dates, and the amounts. */
export function ManualQuotaFields({
  providerId,
  noun,
  placeholders,
  fields,
  fieldErrors,
  pending,
  mode,
  onModeChange,
  onChange,
  providerField,
  amountMode = "usage",
}: ManualQuotaFieldsProps) {
  return (
    <div className="grid grid-cols-1 gap-3">
      {providerField}
      {modeField(providerId, mode, pending, onModeChange)}
      <ManualQuotaField
        id={"manual-quota-start-" + providerId}
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
      <ManualQuotaField
        id={"manual-quota-end-" + providerId}
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
      <ManualQuotaField
        id={"manual-quota-allowance-" + providerId}
        testId="manual-quota-allowance"
        label={"Allowance (" + noun + ")"}
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
      <ManualQuotaField
        id={"manual-quota-usage-" + providerId}
        testId="manual-quota-usage"
        label={
          amountMode === "balance"
            ? "Balance remaining (" + noun + ")"
            : "Current usage (" + noun + ")"
        }
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
}
