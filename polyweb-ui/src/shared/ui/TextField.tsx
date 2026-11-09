import { cn } from "cn"
import { Field } from "./Field"
import { fieldDescribedBy } from "./fieldIds"

interface TextFieldProps {
  id: string
  label: string
  type: "email" | "password" | "text" | "number" | "url" | "date"
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  autoComplete?: string
  /** Accepted input rule or other help, announced with the field. */
  hint?: string
  /** Validation message; it replaces the hint and marks the input invalid. */
  error?: string | null
  placeholder?: string
  required?: boolean
  min?: number | string
  max?: number | string
  maxLength?: number
  /** Monospace value, for keys, ids and endpoints. */
  mono?: boolean
  className?: string
}

/** Labeled text field with the shared surface, focus, hint and error styling. */
export function TextField({
  id,
  label,
  type,
  value,
  onChange,
  hint,
  error,
  mono = false,
  className,
  ...inputProps
}: TextFieldProps) {
  return (
    <Field id={id} label={label} hint={hint} error={error} className={className}>
      <input
        {...inputProps}
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby={fieldDescribedBy(id, hint, error)}
        aria-invalid={error ? true : undefined}
        className={cn("fs-input", type === "number" && "tnum", mono && "font-mono text-[12px]")}
      />
    </Field>
  )
}
