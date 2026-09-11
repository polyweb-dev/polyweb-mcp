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
  render: (inputProps: FieldRenderProps) => ReactNode
}

/** Labeled manual-entry input with inline validation messaging. */
export function ManualQuotaField({ id, testId, label, error, disabled, render }: ManualQuotaFieldProps) {
  const errorId = error ? id + "-error" : undefined
  return (
    <div>
      <label htmlFor={id} className="block text-[12px] text-[var(--muted)] mb-1">
        {label}
      </label>
      {render({
        id,
        "aria-invalid": Boolean(error),
        "aria-describedby": errorId,
        disabled,
        className:
          "w-full rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1.5 text-[13px] text-[var(--text)] tnum outline-none focus-visible:border-[var(--signal)]",
        "data-testid": testId,
      })}
      {error && (
        <p
          id={errorId}
          data-testid={testId + "-error"}
          className="mt-1 text-[12px]"
          style={{ color: "var(--status-danger)" }}
        >
          {error}
        </p>
      )}
    </div>
  )
}
