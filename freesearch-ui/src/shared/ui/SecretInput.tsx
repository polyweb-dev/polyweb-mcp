import { Field } from "./Field"
import { fieldDescribedBy } from "./fieldIds"

interface SecretInputProps {
  id: string
  /** Accessible label, e.g. "API key" or "New API key". */
  label: string
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  hint?: string
  /** Validation message; it replaces the hint and marks the input invalid. */
  error?: string | null
  placeholder?: string
}

/**
 * Write-only secret field.
 *
 * The value is controlled by the owning form's local state only: a password
 * input with autocomplete, spellcheck and autocapitalize off, so the browser
 * never offers, stores or checks it. The owner clears the value after a save
 * (success or failure) and drops it on cancel and unmount.
 */
export function SecretInput({ id, label, value, onChange, disabled = false, hint, error, placeholder }: SecretInputProps) {
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      <input
        id={id}
        name={id}
        type="password"
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        data-1p-ignore
        data-lpignore="true"
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        aria-describedby={fieldDescribedBy(id, hint, error)}
        aria-invalid={error ? true : undefined}
        onChange={(event) => onChange(event.target.value)}
        className="fs-input font-mono text-[12px]"
      />
    </Field>
  )
}
