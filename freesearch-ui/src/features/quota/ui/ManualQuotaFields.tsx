import type { ManualAmountMode, ManualQuotaFieldErrors, ManualQuotaFields } from "../model/manualQuotaMath"
import { ManualQuotaField } from "./ManualQuotaField"

export interface ManualQuotaFieldsProps {
  providerId: string
  noun: string
  placeholders: { allowance: string; used: string }
  fields: ManualQuotaFields
  fieldErrors: ManualQuotaFieldErrors
  pending: boolean
  onChange: (name: keyof ManualQuotaFields, value: string) => void
  /** `balance` labels the second amount as the remaining balance. */
  amountMode?: ManualAmountMode
}

/** Billing window form section: dates plus allowance/usage amounts. */
export function ManualQuotaFields({
  providerId,
  noun,
  placeholders,
  fields,
  fieldErrors,
  pending,
  onChange,
  amountMode = "usage",
}: ManualQuotaFieldsProps) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
