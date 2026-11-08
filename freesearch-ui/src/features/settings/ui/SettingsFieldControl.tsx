import { FIELD_SPECS, numericMax } from "@/domains/settings"
import type { SettingsField, SettingsValue } from "@/domains/settings"
import { Switch } from "@/shared/ui/Switch"
import { EnumSettingControl } from "./EnumSettingControl"
import { ListSettingControl } from "./ListSettingControl"
import { NumberSettingControl } from "./NumberSettingControl"

interface SettingsFieldControlProps {
  field: SettingsField
  value: SettingsValue
  disabled: boolean
  onChange: (value: SettingsValue) => void
  /** Number inputs report whether they hold a value the draft can take. */
  onValidity: (valid: boolean) => void
}

/** Edit one field by its catalog control kind. */
export function SettingsFieldControl({ field, value, disabled, onChange, onValidity }: SettingsFieldControlProps) {
  const spec = FIELD_SPECS[field.id]
  if (spec === undefined) return null
  const { control, label } = spec
  const id = `setting-${field.id}`

  if (control.kind === "boolean") {
    return (
      <div className="flex h-8 items-center">
        <Switch id={id} ariaLabel={label} checked={value === true} disabled={disabled} onChange={onChange} />
      </div>
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
  if (field.id === "trace.retention_days" && control.kind === "number") {
    const max = numericMax(field, control.max)
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Switch
          label="Delete old traces"
          checked={typeof value === "number"}
          disabled={disabled}
          onChange={(checked) => onChange(checked ? Math.min(30, max) : null)}
        />
        {typeof value === "number" && (
          <div className="flex items-center gap-2">
            <span className="text-[var(--muted)]">after</span>
            <div className="w-20">
              <NumberSettingControl
                id={id}
                label="Days"
                value={value}
                bounds={{ ...control, max }}
                suffix="days"
                disabled={disabled}
                onChange={onChange}
                onValidity={onValidity}
              />
            </div>
          </div>
        )}
      </div>
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
      onValidity={onValidity}
    />
  )
}
