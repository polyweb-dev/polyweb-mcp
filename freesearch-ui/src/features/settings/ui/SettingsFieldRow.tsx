import { PROVENANCE_LABELS, fieldLabel, formatSettingsValue } from "@/domains/settings"
import type { SettingsField, SettingsValue } from "@/domains/settings"
import { Button } from "@/shared/ui/button"
import { controlValue, isInheritPending } from "../model/settingsDraft"
import type { SettingsDraft } from "../model/settingsDraft"
import { SettingsFieldControl } from "./SettingsFieldControl"

export const CONSTRAINT_NOTE = "Your override exceeds the system limit; the system limit applies."

interface SettingsFieldRowProps {
  field: SettingsField
  draft: SettingsDraft
  /** Caller holds `settings.write`. */
  editable: boolean
  pending: boolean
  /** Bumped after a save or reload so number and list inputs restart from the value. */
  revision: number
  onChange: (field: SettingsField, value: SettingsValue) => void
  onInherit: (field: SettingsField) => void
}

/** One settings field: effective value, provenance, system default and limit, control. */
export function SettingsFieldRow(props: SettingsFieldRowProps) {
  const { field, draft, editable, pending, revision, onChange, onInherit } = props
  const label = fieldLabel(field.id)
  const canEdit = editable && field.overrideAllowed
  const inheriting = isInheritPending(draft, field)
  const showInherit = canEdit && field.projectOverride !== null && !inheriting

  return (
    <div
      data-testid={`settings-field-${field.id}`}
      className="grid grid-cols-[180px_1fr_auto] items-start gap-4 border-b border-[var(--border-subtle)] py-3 text-[13px]"
    >
      <div>
        <p className="font-medium text-[var(--text-strong)]">{label}</p>
        <span className="mt-1 inline-block rounded border border-[var(--border-subtle)] px-1.5 py-0.5 text-[11px] text-[var(--muted)]">
          {PROVENANCE_LABELS[field.provenance]}
        </span>
      </div>
      <div className="space-y-1">
        <p className="text-[var(--text)]">{formatSettingsValue(field.id, field.effectiveValue)}</p>
        <p className="text-[12px] text-[var(--muted)]">
          System default: {formatSettingsValue(field.id, field.systemDefault)}
        </p>
        {field.systemLimit !== null && (
          <p className="text-[12px] text-[var(--muted)]">
            System limit: {formatSettingsValue(field.id, field.systemLimit)}
          </p>
        )}
        {field.constraintApplied && <p className="text-[12px] text-[var(--status-warning)]">{CONSTRAINT_NOTE}</p>}
        {!field.overrideAllowed && <p className="text-[12px] text-[var(--muted)]">Set by system</p>}
        {inheriting && <p className="text-[12px] text-[var(--muted)]">Inherits the system default after saving.</p>}
      </div>
      <div className="flex items-start gap-2">
        {canEdit && (
          <SettingsFieldControl
            key={`${revision}:${inheriting ? "inherit" : "value"}`}
            field={field}
            value={controlValue(draft, field)}
            disabled={pending}
            onChange={(value) => onChange(field, value)}
          />
        )}
        {showInherit && (
          <Button size="sm" variant="outline" aria-label={`Inherit ${label}`} disabled={pending} onClick={() => onInherit(field)}>
            Inherit
          </Button>
        )}
      </div>
    </div>
  )
}
