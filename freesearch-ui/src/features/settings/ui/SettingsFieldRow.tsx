import { disabledOptionReason, fieldLabel } from "@/domains/settings"
import type { SettingsField, SettingsValue } from "@/domains/settings"
import { controlValue, isInheritPending } from "../model/settingsDraft"
import type { SettingsDraft } from "../model/settingsDraft"
import { valueText } from "../model/settingsFormat"
import { SETTING_CONTROL_COLUMN } from "./settingControlStyles"
import { SettingsFieldControl } from "./SettingsFieldControl"
import { SettingsFieldHint } from "./SettingsFieldHint"

export const CONSTRAINT_NOTE = "Your override exceeds the system limit. The system limit applies"

interface SettingsFieldRowProps {
  field: SettingsField
  draft: SettingsDraft
  /** Caller holds `settings.write`. */
  editable: boolean
  pending: boolean
  /** Bumped after a save, discard or reload so number inputs restart from the value. */
  generation: number
  onChange: (field: SettingsField, value: SettingsValue) => void
  onInherit: (field: SettingsField) => void
  /** Whether the field's input holds a value the draft can take. */
  onValidity: (fieldId: string, valid: boolean) => void
}

function traceHelp(field: SettingsField, draft: SettingsDraft): string | null {
  if (field.id === "trace.detail") {
    return "API keys, auth headers, cookies, passwords and tokens are always removed from traces"
  }
  if (field.id === "trace.retention_days") {
    return controlValue(draft, field) === null
      ? "Traces stay until you delete them"
      : "The system can delete traces after this limit"
  }
  return null
}

/**
 * One settings field on one line: the label (and a quiet hint only when the
 * project overrides it) on the left, the control in a fixed-width column on
 * the right. An editor sees the control; a reader sees the value as text.
 */
export function SettingsFieldRow(props: SettingsFieldRowProps) {
  const { field, draft, editable, pending, generation, onChange, onInherit, onValidity } = props
  const canEdit = editable && field.overrideAllowed
  const inheriting = isInheritPending(draft, field)
  const limitedDetail = field.id === "trace.detail" && disabledOptionReason(field, "full") !== null
  const retention = field.id === "trace.retention_days"
  const help = traceHelp(field, draft)

  return (
    <div
      data-testid={`settings-field-${field.id}`}
      className="flex items-start justify-between gap-8 px-4 py-3 text-[13px]"
    >
      <div className="min-w-0 space-y-1 pt-1">
        <p className="leading-5 font-medium text-[var(--text-strong)]">{fieldLabel(field.id)}</p>
        {help !== null && <p className="text-[12px] text-[var(--muted)]">{help}</p>}
        {limitedDetail && <p className="text-[12px] text-[var(--muted)]">The system limit is metadata only</p>}
        {!retention && field.id !== "trace.detail" && <SettingsFieldHint
          field={field}
          inheriting={inheriting}
          canReset={canEdit}
          pending={pending}
          onReset={() => onInherit(field)}
        />}
        {field.constraintApplied && <p className="text-[12px] leading-4 text-[var(--status-warning)]">{CONSTRAINT_NOTE}</p>}
      </div>
      <div className={SETTING_CONTROL_COLUMN}>
        {canEdit && !limitedDetail ? (
          <SettingsFieldControl
            key={`${generation}:${inheriting ? "inherit" : "value"}`}
            field={field}
            value={controlValue(draft, field)}
            disabled={pending}
            onChange={(value) => onChange(field, value)}
            onValidity={(valid) => onValidity(field.id, valid)}
          />
        ) : (
          <p className="flex h-8 items-center text-[var(--text)] tnum">{valueText(field.id, field.effectiveValue)}</p>
        )}
      </div>
    </div>
  )
}
