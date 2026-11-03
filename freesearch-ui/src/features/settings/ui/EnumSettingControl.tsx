import { disabledOptionReason } from "@/domains/settings"
import type { EnumOption, SettingsField } from "@/domains/settings"
import { SETTING_FIELD_CLASS } from "./settingControlStyles"

interface EnumSettingControlProps {
  id: string
  label: string
  field: SettingsField
  options: readonly EnumOption[]
  value: string
  disabled: boolean
  onChange: (value: string) => void
}

/** Select of one enum field; options looser than the system are disabled with the reason. */
export function EnumSettingControl(props: EnumSettingControlProps) {
  const { id, label, field, options, value, disabled, onChange } = props
  const reasons = options
    .map((option) => disabledOptionReason(field, option.value))
    .filter((reason): reason is string => reason !== null)
  return (
    <div className="space-y-1">
      <select
        id={id}
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className={SETTING_FIELD_CLASS}
      >
        {options.map((option) => (
          <option
            key={option.value}
            value={option.value}
            disabled={disabledOptionReason(field, option.value) !== null}
          >
            {option.label}
          </option>
        ))}
      </select>
      {reasons.map((reason) => (
        <p key={reason} className="text-[12px] text-[var(--muted)]">
          {reason}
        </p>
      ))}
    </div>
  )
}
