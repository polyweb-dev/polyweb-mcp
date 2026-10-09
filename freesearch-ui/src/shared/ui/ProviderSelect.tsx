import type { ReactNode } from "react"
import { CircleUserRound, Layers, Sparkles } from "lucide-react"
import type { LucideIcon } from "lucide-react"
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

/** The size and the color of every entry mark. */
const MARK_CLASS = "size-4 shrink-0 text-[var(--muted)]"

/** The mark of the shown value, which inherits the white of the signal row. */
const MARK_CLASS_SELECTED = "size-4 shrink-0"

/**
 * The thematic mark of each routing entry. Auto arbitration shows the
 * arbitration spark; All Providers shows the fused provider layers.
 */
const SENTINEL_MARKS: Record<string, LucideIcon> = {
  auto: Sparkles,
  all: Layers,
}

/**
 * The mark of one entry without a catalog logo: the thematic mark of a routing
 * entry, else the generic account icon.
 */
function entryMark(value: string, selected: boolean): ReactNode {
  const Mark = SENTINEL_MARKS[value] ?? CircleUserRound
  return (
    <Mark
      aria-hidden="true"
      data-testid="provider-select-mark"
      className={selected ? MARK_CLASS_SELECTED : MARK_CLASS}
    />
  )
}

/** One entry of the list: the catalog logo and the name, else the entry mark. */
function pickerRow(option: SelectOption, selected = false): ReactNode {
  return (
    <ProviderBadge
      providerId={option.value}
      name={option.label}
      className="shrink-0"
      logoClassName="size-4"
      fallback={entryMark(option.value, selected)}
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
 * shows a thematic mark, and any other such provider shows the account icon.
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
      renderOption={(option, state) => pickerRow(option, state.selected)}
    />
  )
}
