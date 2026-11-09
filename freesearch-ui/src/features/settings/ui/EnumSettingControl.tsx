import { disabledOptionReason } from "@/domains/settings"
import type { EnumOption, SettingsField } from "@/domains/settings"
import { Select } from "@/shared/ui/select"
import type { SelectOption } from "@/shared/ui/select"

interface EnumSettingControlProps {
  id: string
  label: string
  field: SettingsField
  options: readonly EnumOption[]
  value: string
  disabled: boolean
  onChange: (value: string) => void
}

/** "The system allows metadata only." → "The system allows metadata only" */
function phrase(reason: string): string {
  return reason.replace(/\.$/, "")
}

/** Select of one enum field; an option looser than the system is disabled with its reason. */
export function EnumSettingControl(props: EnumSettingControlProps) {
  const { id, label, field, options, value, disabled, onChange } = props
  const rows: SelectOption[] = options.map((option) => {
    const reason = disabledOptionReason(field, option.value)
    return reason === null
      ? { value: option.value, label: option.label }
      : { value: option.value, label: option.label, disabled: true, description: phrase(reason) }
  })
  return (
    <Select
      id={id}
      ariaLabel={label}
      value={value}
      options={rows}
      disabled={disabled}
      onValueChange={onChange}
    />
  )
}
