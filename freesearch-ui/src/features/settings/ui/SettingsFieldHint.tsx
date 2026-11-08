import { fieldLabel } from "@/domains/settings"
import type { SettingsField } from "@/domains/settings"
import { Button } from "@/shared/ui/button"
import { valueText } from "../model/settingsFormat"

interface SettingsFieldHintProps {
  field: SettingsField
  /** The draft resets this override to the system default on save. */
  inheriting: boolean
  /** The caller may reset the override (`settings.write` and override allowed). */
  canReset: boolean
  pending: boolean
  onReset: () => void
}

/** Where a non-default value comes from; `null` for a value that follows the system. */
function originText(field: SettingsField, inheriting: boolean): string | null {
  if (!field.overrideAllowed) return "Set by system"
  if (inheriting) return "System default after saving"
  if (field.projectOverride === null) return null
  return `Overridden · default ${valueText(field.id, field.systemDefault)}`
}

/**
 * Quiet hint line of one field, shown only when the value does not simply
 * follow the system: "Overridden · default 30 · Reset", "Set by system", or
 * the pending reset. A value that follows the system default has no hint.
 */
export function SettingsFieldHint({ field, inheriting, canReset, pending, onReset }: SettingsFieldHintProps) {
  const origin = originText(field, inheriting)
  if (origin === null) return null
  const showReset = canReset && field.projectOverride !== null && !inheriting
  return (
    <p className="flex flex-wrap items-center gap-x-1 text-[12px] leading-4 text-[var(--muted)]">
      <span>{origin}</span>
      {showReset && (
        <>
          <span aria-hidden="true">·</span>
          <Button
            variant="link"
            size="xs"
            className="h-4 px-0 text-[12px] font-normal"
            aria-label={`Reset ${fieldLabel(field.id)}`}
            disabled={pending}
            onClick={onReset}
          >
            Reset
          </Button>
        </>
      )}
    </p>
  )
}
