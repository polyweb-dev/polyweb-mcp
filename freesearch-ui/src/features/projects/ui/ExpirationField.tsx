import { SegmentedControl } from "@/shared/ui/SegmentedControl"
import { DateField } from "@/shared/ui/DateField"
import { todayInputValue, type ExpiryChoice } from "../model/expiryChoice"

const NEVER_LABEL = "No expiration"
const CUSTOM_LABEL = "Custom date"
const NEVER_HINT = "The key works until you revoke it"
const CUSTOM_HINT = "Enter YYYY-MM-DD. The key stops working at the end of this day"

export interface ExpirationFieldProps {
  /** Unique prefix of the element ids. */
  idPrefix: string
  /** Label of the `default` segment ("90 days" or "Keep current"). */
  defaultLabel: string
  /** Hint line shown while the `default` segment is selected. */
  defaultHint: string
  choice: ExpiryChoice
  customDate: string
  disabled: boolean
  /** Validation message of the custom date. */
  error?: string | null
  onChoiceChange: (choice: ExpiryChoice) => void
  onCustomDateChange: (value: string) => void
}

/**
 * Expiration control of the issue form and the rotate dialog: a segmented
 * choice with one hint line for the selected option. "No expiration" is an
 * explicit choice; "Custom date" reveals a date field whose earliest value is
 * today.
 */
export function ExpirationField({
  idPrefix,
  defaultLabel,
  defaultHint,
  choice,
  customDate,
  disabled,
  error = null,
  onChoiceChange,
  onCustomDateChange,
}: ExpirationFieldProps) {
  const labels: Record<ExpiryChoice, string> = { default: defaultLabel, never: NEVER_LABEL, custom: CUSTOM_LABEL }
  const choices: ExpiryChoice[] = ["default", "never", "custom"]

  return (
    <div>
      <p className="fs-label">Expiration</p>
      <SegmentedControl
        ariaLabel="Expiration"
        options={choices.map((value) => labels[value])}
        value={labels[choice]}
        disabled={disabled}
        onChange={(label) => onChoiceChange(choices.find((value) => labels[value] === label) ?? "default")}
      />
      {choice === "custom" ? (
        <DateField
          id={`${idPrefix}-expiration-date`}
          label="Expiration date"
          placeholder={todayInputValue()}
          value={customDate}
          onChange={onCustomDateChange}
          disabled={disabled}
          hint={CUSTOM_HINT}
          error={error}
          className="mt-3 w-48"
        />
      ) : (
        <p className="fs-hint">{choice === "never" ? NEVER_HINT : defaultHint}</p>
      )}
    </div>
  )
}
