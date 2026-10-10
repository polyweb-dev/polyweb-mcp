interface TextFieldProps {
  id: string
  label: string
  type: "email" | "password" | "text"
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  autoComplete?: string
  /** Accepted input rule or other help, announced with the field. */
  hint?: string
}

/** Labeled text field with the shared surface, focus, and hint styling. */
export function TextField({
  id,
  label,
  type,
  value,
  onChange,
  disabled = false,
  autoComplete,
  hint,
}: TextFieldProps) {
  const hintId = hint === undefined ? undefined : `${id}-hint`
  return (
    <div>
      <label htmlFor={id} className="block text-[12px] text-[var(--muted)] mb-1">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        {...(autoComplete === undefined ? {} : { autoComplete })}
        {...(hintId === undefined ? {} : { "aria-describedby": hintId })}
        className="w-full rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1.5 text-[13px] text-[var(--text)] outline-none focus-visible:border-[var(--signal)] disabled:opacity-60"
      />
      {hint !== undefined && (
        <p id={hintId} className="mt-1 text-[12px] text-[var(--muted)]">
          {hint}
        </p>
      )}
    </div>
  )
}
