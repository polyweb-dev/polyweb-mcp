import type { ReactNode } from "react"
import { cn } from "cn"

export interface FieldProps {
  /** Id of the control inside; the label points at it. */
  id: string
  label: ReactNode
  hint?: ReactNode
  error?: string | null
  className?: string
  children: ReactNode
}

/**
 * The one labeled-field layout: label above, the control, then a hint or an
 * error below. Wrap any control (input, Select, SecretInput) in it so every
 * form shares one label, hint and error style.
 */
export function Field({ id, label, hint, error, className, children }: FieldProps) {
  return (
    <div className={cn("min-w-0", className)}>
      <label htmlFor={id} className="fs-label">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} role="alert" className="fs-field-error">
          {error}
        </p>
      ) : (
        hint && (
          <p id={`${id}-hint`} className="fs-hint">
            {hint}
          </p>
        )
      )}
    </div>
  )
}
