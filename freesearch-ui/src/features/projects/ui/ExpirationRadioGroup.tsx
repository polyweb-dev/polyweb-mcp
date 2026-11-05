import { todayInputValue, type ExpiryChoice } from "../model/expiryChoice"

const RADIO_ROW = "flex items-center gap-2 text-[13px] text-[var(--text)]"

export interface ExpirationRadioGroupProps {
  /** Unique prefix for the radio name and the element ids. */
  idPrefix: string
  /** Label of the `default` option ("90 days (default)" or "Keep current lifetime"). */
  defaultLabel: string
  choice: ExpiryChoice
  customDate: string
  disabled: boolean
  onChoiceChange: (choice: ExpiryChoice) => void
  onCustomDateChange: (value: string) => void
}

/**
 * Expiration radio group of the issue form and the rotate dialog.
 *
 * "No expiration" is an explicit choice. "Custom date" reveals a date input
 * whose earliest value is today.
 */
export function ExpirationRadioGroup({
  idPrefix,
  defaultLabel,
  choice,
  customDate,
  disabled,
  onChoiceChange,
  onCustomDateChange,
}: ExpirationRadioGroupProps) {
  const options: { value: ExpiryChoice; label: string }[] = [
    { value: "default", label: defaultLabel },
    { value: "never", label: "No expiration" },
    { value: "custom", label: "Custom date" },
  ]
  const legendId = `${idPrefix}-expiration-legend`
  const dateId = `${idPrefix}-expiration-date`

  return (
    <div className="space-y-2">
      <p id={legendId} className="text-[12px] text-[var(--muted)]">
        Expiration
      </p>
      <div
        role="radiogroup"
        aria-labelledby={legendId}
        className="flex flex-wrap items-center gap-x-4 gap-y-1.5"
      >
        {options.map((option) => (
          <label key={option.value} className={RADIO_ROW}>
            <input
              type="radio"
              name={`${idPrefix}-expiration`}
              value={option.value}
              checked={choice === option.value}
              disabled={disabled}
              onChange={() => onChoiceChange(option.value)}
              className="accent-[var(--signal)]"
            />
            <span>{option.label}</span>
          </label>
        ))}
        {choice === "custom" && (
          <span className="flex items-center gap-2">
            <label htmlFor={dateId} className="sr-only">
              Expiration date
            </label>
            <input
              id={dateId}
              type="date"
              min={todayInputValue()}
              value={customDate}
              disabled={disabled}
              onChange={(event) => onCustomDateChange(event.target.value)}
              className="rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1 text-[13px] text-[var(--text)] outline-none focus-visible:border-[var(--signal)] disabled:opacity-60"
            />
          </span>
        )}
      </div>
    </div>
  )
}
