import type { ReactNode } from "react"
import { cn } from "cn"
import { Field } from "./Field"

export function NumericField({ id, label, value, onChange, onBlur, min, step, prefix, error, disabled, testId, hint }: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  onBlur?: () => void
  min?: number | string
  step?: number | string
  error?: string | undefined
  prefix?: string
  disabled?: boolean
  testId?: string
  hint?: ReactNode
}) {
  return <Field id={id} label={label} error={error ?? null} hint={hint}>
    <div className="relative">
      {prefix && <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-[var(--muted)]">{prefix}</span>}
      <input id={id} type="number" disabled={disabled} data-testid={testId} aria-invalid={error ? true : undefined} aria-describedby={error ? id + "-error" : hint ? id + "-hint" : undefined} min={min} step={step} value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        className={cn("fs-input tnum [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none", prefix && "pl-7")} />
    </div>
  </Field>
}
