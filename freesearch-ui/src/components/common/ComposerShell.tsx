import type { ReactNode } from "react"

interface ComposerShellProps {
  testIdPrefix: string
  inputRow: ReactNode
  footer?: ReactNode
}

export function ComposerShell({
  testIdPrefix,
  inputRow,
  footer,
}: ComposerShellProps) {
  return (
    <div
      data-testid={`${testIdPrefix}-composer`}
      className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--elevated)] p-4 shadow-lg transition-all transition-colors focus-within:border-[var(--signal)]/60 motion-reduce:transition-none"
    >
      {inputRow}
      {footer && (
        <>
          <hr
            data-testid={`${testIdPrefix}-composer-divider`}
            className="mt-3 border-0 border-t border-[var(--border-subtle)] pt-3"
          />
          <div
            data-testid={`${testIdPrefix}-composer-footer`}
            className="space-y-3 text-[13px] text-[var(--muted)]"
          >
            {footer}
          </div>
        </>
      )}
    </div>
  )
}
