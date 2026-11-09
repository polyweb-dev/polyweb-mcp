import type { BudgetPeriod } from "@/shared/lib/budget"
import { Field } from "./Field"
import { NumericField } from "./NumericField"
import { Select } from "./select"

export function BudgetFields({ id, label, amount, onAmountChange, period, onPeriodChange, error }: {
  error?: string | undefined
  id: string
  label: string
  amount: string
  onAmountChange: (value: string) => void
  period: BudgetPeriod
  onPeriodChange: (value: BudgetPeriod) => void
}) {
  const periodId = `${id}-period`
  return <div className="grid grid-cols-2 gap-3">
    <NumericField id={id} label={label} min="0" step="0.000001" prefix="$" value={amount} onChange={onAmountChange} error={error} />
    <Field id={periodId} label="Budget period"><Select id={periodId} value={period}
      onValueChange={(value) => onPeriodChange(value === "day" || value === "week" ? value : "month")}
      options={[{ value: "day", label: "Per day" }, { value: "week", label: "Per week" }, { value: "month", label: "Per month" }]} /></Field>
  </div>
}
