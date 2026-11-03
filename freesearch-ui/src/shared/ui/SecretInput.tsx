interface SecretInputProps {
  id: string
  /** Accessible label, e.g. "API key" or "New API key". */
  label: string
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

/**
 * Write-only secret field.
 *
 * The value is controlled by the owning form's local state only: a password
 * input with autocomplete, spellcheck and autocapitalize off, so the browser
 * never offers, stores or checks it. The owner clears the value after a save
 * (success or failure) and drops it on cancel and unmount.
 */
export function SecretInput({ id, label, value, onChange, disabled = false }: SecretInputProps) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-[12px] text-[var(--muted)]">
        {label}
      </label>
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
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1.5 font-mono text-[13px] text-[var(--text)] outline-none focus-visible:border-[var(--signal)] disabled:opacity-60"
      />
    </div>
  )
}
