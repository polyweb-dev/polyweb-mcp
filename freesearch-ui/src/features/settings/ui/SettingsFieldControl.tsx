import { FIELD_SPECS, numericMax } from "@/domains/settings"
import type { SettingsField, SettingsValue } from "@/domains/settings"
import { EnumSettingControl } from "./EnumSettingControl"
import { ListSettingControl } from "./ListSettingControl"
import { NumberSettingControl } from "./NumberSettingControl"

interface SettingsFieldControlProps {
  field: SettingsField
  value: SettingsValue
  disabled: boolean
  onChange: (value: SettingsValue) => void
}

/** Edit control of one field, by its catalog control kind. */
export function SettingsFieldControl({ field, value, disabled, onChange }: SettingsFieldControlProps) {
  const spec = FIELD_SPECS[field.id]
  if (spec === undefined) return null
  const { control, label } = spec
  const id = `setting-${field.id}`

  if (control.kind === "boolean") {
    return (
      <label className="inline-flex items-center gap-2 text-[13px]">
        <input
          id={id}
          type="checkbox"
          aria-label={label}
          checked={value === true}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        {value === true ? "On" : "Off"}
      </label>
    )
  }
  if (control.kind === "enum") {
    return (
      <EnumSettingControl
        id={id}
        label={label}
        field={field}
        options={control.options}
        value={typeof value === "string" ? value : ""}
        disabled={disabled}
        onChange={onChange}
      />
    )
  }
  if (control.kind === "list") {
    return (
      <ListSettingControl
        id={id}
        label={label}
        value={Array.isArray(value) ? value : []}
        disabled={disabled}
        onChange={onChange}
      />
    )
  }
  return (
    <NumberSettingControl
      id={id}
      label={label}
      value={typeof value === "number" ? value : null}
      bounds={{ ...control, max: numericMax(field, control.max) }}
      disabled={disabled}
      onChange={onChange}
    />
  )
}
