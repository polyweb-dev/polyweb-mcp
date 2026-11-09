import type { ReactNode } from "react"

export interface FieldRenderProps {
  id: string
  "aria-invalid": boolean
  "aria-describedby": string | undefined
  disabled: boolean
  className: string
  "data-testid": string
}

export interface ManualQuotaFieldProps {
  id: string
  testId: string
  label: string
  error: string | undefined
  disabled: boolean
  meta?: ReactNode
  hint?: string
  render: (inputProps: FieldRenderProps) => ReactNode
}

/**
 * Labeled manual-entry control with inline validation, in the shared field
 * look (`fs-label`, `fs-input`, `fs-field-error`). It keeps its own test ids
 * on the control and the error line.
 */
export function ManualQuotaField({ id, testId, label, error, disabled, render, meta, hint }: ManualQuotaFieldProps) {
  const errorId = error ? id + "-error" : undefined
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2"><label htmlFor={id} className="fs-label">
        {label}
      </label>{meta}</div>
      {render({
        id,
        "aria-invalid": Boolean(error),
        "aria-describedby": errorId ?? (hint ? id + "-hint" : undefined),
        disabled,
        className: "fs-input tnum",
        "data-testid": testId,
      })}
      {hint && <p id={id + "-hint"} className="fs-hint">{hint}</p>}
      {error && (
        <p id={errorId} data-testid={testId + "-error"} className="fs-field-error">
          {error}
        </p>
      )}
    </div>
  )
}
