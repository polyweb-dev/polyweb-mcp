import type { ReactNode } from "react"
import { Select, type SelectOption } from "@/shared/ui/select"
import { NumericField } from "@/shared/ui/NumericField"
import { formatPercent1dp } from "../model/manualQuotaMath"
import type { ManualAmountMode, ManualQuotaFieldErrors, ManualQuotaFields } from "../model/manualQuotaMath"
import {
  CREDIT_MODE_FIELD,
  CREDIT_MODE_LABEL,
  CREDIT_MODES,
  type CreditMode,
} from "../model/quotaLabels"
import { ManualQuotaField } from "./ManualQuotaField"
import { QuotaDateField } from "./QuotaDateField"

const BALANCE_MODE_LABEL: Record<CreditMode, string> = {
  free: "Free balance",
  paid: "Paid balance",
  both: "Free and paid balances",
}

function usesNativeCredits(providerId: string): boolean {
  return providerId === "firecrawl" || providerId === "tavily"
}

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
  preview?: number | null
}

/** The mode combo of one manual entry. */
function modeField(
  providerId: string,
  mode: CreditMode,
  pending: boolean,
  onModeChange: (mode: CreditMode) => void,
) {
  const labels = usesNativeCredits(providerId) ? CREDIT_MODE_LABEL : BALANCE_MODE_LABEL
  const options: SelectOption[] = CREDIT_MODES.map((option) => ({
    value: option,
    label: labels[option],
  }))
  return (
    <ManualQuotaField
      id={"manual-quota-mode-" + providerId}
      testId="manual-quota-mode"
      label={CREDIT_MODE_FIELD}
      error={undefined}
      disabled={pending}
      render={(inputProps) => (
        <Select
          id={inputProps.id}
          testId={inputProps["data-testid"]}
          value={mode}
          options={options}
          disabled={inputProps.disabled}
          onValueChange={(next) => {
            const chosen = CREDIT_MODES.find((option) => option === next)
            if (chosen !== undefined) onModeChange(chosen)
          }}
        />
      )}
    />
  )
}

/** Billing window form section: the provider, the credit mode, the dates, and the amounts. */
export function ManualQuotaFields({
  providerId,
  noun,
  fields,
  fieldErrors,
  pending,
  mode,
  onModeChange,
  onChange,
  providerField,
  amountMode = "usage",
  preview = null,
}: ManualQuotaFieldsProps) {
  const nativeCredits = mode === "free" && usesNativeCredits(providerId)
  const unit = nativeCredits ? "credits" : usesNativeCredits(providerId) ? "USD" : noun
  return (
    <div className="grid grid-cols-1 gap-3">
      {providerField}
      {modeField(providerId, mode, pending, onModeChange)}
      <div role="group" aria-label="Billing dates" className="space-y-1">
        <div className="grid grid-cols-2 gap-3">
          <QuotaDateField
            id={"manual-quota-start-" + providerId}
            label="Billing start"
            value={fields.billingStart}
            error={fieldErrors.billingStart}
            disabled={pending}
            onChange={(value) => onChange("billingStart", value)}
          />
          <QuotaDateField
            id={"manual-quota-end-" + providerId}
            label="Billing end"
            value={fields.billingEnd}
            error={fieldErrors.billingEnd}
            disabled={pending}
            onChange={(value) => onChange("billingEnd", value)}
          />
        </div>
      </div>
      <NumericField
        id={"manual-quota-allowance-" + providerId}
        testId="manual-quota-allowance"
        label={"Allowance (" + unit + ")"}
        error={fieldErrors.allowance}
        disabled={pending}
        value={fields.allowance}
        min="0"
        step="any"
        {...(unit === "USD" ? { prefix: "$" } : {})}
        onChange={(value) => onChange("allowance", value)}
      />
      <NumericField
        id={"manual-quota-usage-" + providerId}
        testId="manual-quota-usage"
        label={
          amountMode === "balance"
            ? nativeCredits ? "Credits left" : "Balance remaining (" + unit + ")"
            : "Current usage (" + unit + ")"
        }
        error={fieldErrors.used}
        hint={preview === null ? null : <span data-testid="manual-quota-preview" aria-live="polite" className="tnum">{formatPercent1dp(preview)}% remaining</span>}
        disabled={pending}
        value={fields.used}
        min="0"
        step="any"
        {...(unit === "USD" ? { prefix: "$" } : {})}
        onChange={(value) => onChange("used", value)}
      />
    </div>
  )
}
