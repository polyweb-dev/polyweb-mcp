import type { CopyBinding } from "@/domains/settings"
import { Checkbox } from "@/shared/ui/Checkbox"

interface CopyBindingChoicesProps {
  bindings: readonly CopyBinding[]
  selected: ReadonlySet<string>
  disabled: boolean
  onToggle: (bindingId: string, on: boolean) => void
}

/** Routes of the source project to copy too; one that cannot be copied is disabled with the reason. */
export function CopyBindingChoices({ bindings, selected, disabled, onToggle }: CopyBindingChoicesProps) {
  if (bindings.length === 0) return null
  return (
    <fieldset>
      <legend className="fs-label">Also copy routes</legend>
      <div className="flex flex-col gap-2">
        {bindings.map((binding) => (
          <Checkbox
            key={binding.bindingId}
            checked={binding.eligible && selected.has(binding.bindingId)}
            disabled={disabled || !binding.eligible}
            label={binding.routeLabel}
            {...(!binding.eligible && binding.rejection !== null ? { description: binding.rejection } : {})}
            onChange={(on) => onToggle(binding.bindingId, on)}
          />
        ))}
      </div>
    </fieldset>
  )
}
