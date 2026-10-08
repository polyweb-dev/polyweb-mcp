import type { ReactNode } from "react"
import { CircleUserRound } from "lucide-react"
import { ProviderBadge } from "./ProviderBadge"
import { Select, type SelectOption } from "./select"

export interface ProviderSelectProps {
  id?: string
  testId?: string
  value: string
  /**
   * The selectable entries of the picker. Each value is a provider id or a
   * routing sentinel, and each label is the name the operator reads.
   */
  options: SelectOption[]
  onValueChange: (value: string) => void
  disabled?: boolean
  className?: string
}

/** The mark of an entry without a catalog logo, such as Auto arbitration. */
function accountMark(): ReactNode {
  return (
    <CircleUserRound
      aria-hidden="true"
      data-testid="provider-select-account"
      className="size-4 shrink-0 text-[var(--muted)]"
    />
  )
}

/** One entry of the list: the catalog logo and the name, else the account icon. */
function pickerRow(option: SelectOption): ReactNode {
  return (
    <ProviderBadge
      providerId={option.value}
      name={option.label}
      className="shrink-0"
      logoClassName="size-4"
      fallback={accountMark()}
    />
  )
}

/**
 * The one provider dropdown of the application: every entry shows its identity
 * mark and its name. The balance entry modal, the Search Playground, and the
 * Fetch Playground share this component, so the picker has one implementation.
 *
 * The shared `Select` supplies the combobox roles and the keyboard access. An
 * entry without a catalog logo, such as Auto arbitration or All Providers,
 * shows the generic account icon.
 */
export function ProviderSelect({
  id,
  testId,
  value,
  options,
  onValueChange,
  disabled,
  className,
}: ProviderSelectProps): ReactNode {
  /** The entry of the shown value; an unknown value shows its own id. */
  const shownOf = (current: string): SelectOption =>
    options.find((option) => option.value === current) ?? { value: current, label: current }
  return (
    <Select
      id={id}
      testId={testId}
      value={value}
      options={options}
      onValueChange={onValueChange}
      disabled={disabled}
      className={className}
      renderValue={(current) => pickerRow(shownOf(current))}
      renderOption={pickerRow}
    />
  )
}
