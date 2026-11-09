import { DateField } from "@/shared/ui/DateField"

interface QuotaDateFieldProps {
  id: string
  label: string
  value: string
  error: string | undefined
  disabled: boolean
  onChange: (value: string) => void
}

export function QuotaDateField({ id, label, value, error, disabled, onChange }: QuotaDateFieldProps) {
  return (
    <DateField
      id={id}
      label={label}
      value={value}
      error={error ?? null}
      disabled={disabled}
      placeholder="YYYY-MM-DD"
      onChange={onChange}
    />
  )
}
