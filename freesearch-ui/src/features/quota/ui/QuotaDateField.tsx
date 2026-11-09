import { useState } from "react"
import { formatDate } from "@/shared/lib/formatTime"
import { TextField } from "@/shared/ui/TextField"

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

function dateValue(text: string): string {
  const match = /^([a-z]{3})\s+(\d{1,2}),?\s+(\d{4})$/i.exec(text.trim())
  if (match === null) return text
  const month = MONTHS.indexOf(match[1].toLowerCase()) + 1
  const day = Number(match[2])
  const year = Number(match[3])
  const date = new Date(Date.UTC(year, month - 1, day))
  if (month === 0 || date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return text
  return `${match[3]}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`
}

interface QuotaDateFieldProps {
  id: string
  label: string
  value: string
  error: string | undefined
  disabled: boolean
  onChange: (value: string) => void
}

export function QuotaDateField({ id, label, value, error, disabled, onChange }: QuotaDateFieldProps) {
  const [text, setText] = useState(() => value ? formatDate(value + "T00:00:00") : "")
  return (
    <TextField
      id={id}
      label={label}
      type="text"
      value={text}
      error={error ?? null}
      disabled={disabled}
      onChange={(next) => {
        setText(next)
        onChange(dateValue(next))
      }}
    />
  )
}
