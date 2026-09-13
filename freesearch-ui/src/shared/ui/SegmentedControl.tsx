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
  /** Optional minimum column width override, defaults to 80px. */
  minColumnWidth?: string
  /** Disables every segment button while an operation is in flight. */
  disabled?: boolean
}

/**
 * Exclusive toggle-button group. Exactly one button exposes
 * `aria-pressed="true"`; the rest expose `aria-pressed="false"`.
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
      className="inline-flex items-center gap-0.5 rounded-md border border-[var(--border-subtle)] p-0.5"
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
              "min-w-[80px] rounded px-3 py-1 text-[13px] font-medium transition-colors motion-reduce:transition-none",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40",
              "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
              isSelected
                ? "bg-[var(--signal-muted)] text-[var(--signal)]"
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
