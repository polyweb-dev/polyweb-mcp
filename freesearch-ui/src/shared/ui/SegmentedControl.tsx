import React from "react"
import { cn } from "cn"

export interface SegmentedControlProps {
  /** Exclusive choices, rendered left to right in the given order. */
  options: readonly string[]
  /** The currently selected option value. */
  value: string
  onChange: (value: string) => void
  /** Accessible group label (also announced with each toggle button). */
  ariaLabel: string
  /** Optional minimum column width override; segments size to their label by default. */
  minColumnWidth?: string
  /** Disables every segment button while an operation is in flight. */
  disabled?: boolean
}

/**
 * Exclusive toggle-button group. Exactly one button exposes
 * `aria-pressed="true"`; the rest expose `aria-pressed="false"`. The
 * selected segment is one neutral surface step, not an accent fill.
 */
export const SegmentedControl: React.FC<SegmentedControlProps> = ({
  options,
  value,
  onChange,
  ariaLabel,
  minColumnWidth,
  disabled = false,
}) => {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="inline-flex h-8 max-w-full items-center gap-0.5 rounded-md border border-[var(--border-subtle)] bg-[var(--surface)] p-0.5"
    >
      {options.map((option) => {
        const isSelected = option === value
        return (
          <button
            key={option}
            type="button"
            aria-pressed={isSelected}
            onClick={() => onChange(option)}
            disabled={disabled}
            className={cn(
              "h-full rounded-[4px] px-3 text-[13px] transition-colors motion-reduce:transition-none",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40",
              "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
              isSelected
                ? "bg-[var(--raised)] font-medium text-[var(--text-strong)] shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]"
                : "text-[var(--muted)] hover:text-[var(--text-strong)]"
            )}
            style={minColumnWidth ? { minWidth: minColumnWidth } : undefined}
          >
            {option}
          </button>
        )
      })}
    </div>
  )
}
