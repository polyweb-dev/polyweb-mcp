import { cn } from "cn"
import { Field } from "./Field"

export function NumericField({ id, label, value, onChange, min, step, prefix, error }: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  min?: number | string
  step?: number | string
  error?: string | undefined
  prefix?: string
}) {
  return <Field id={id} label={label} error={error ?? null}>
    <div className="relative">
      {prefix && <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-[var(--muted)]">{prefix}</span>}
      <input id={id} type="number" aria-invalid={error ? true : undefined} aria-describedby={error ? id + "-error" : undefined} min={min} step={step} value={value}
        onChange={(event) => onChange(event.target.value)}
        className={cn("fs-input tnum [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none", prefix && "pl-7")} />
    </div>
  </Field>
}
