import type { CopyBinding } from "@/domains/settings"

interface CopyBindingChoicesProps {
  bindings: readonly CopyBinding[]
  selected: ReadonlySet<string>
  disabled: boolean
  onToggle: (bindingId: string, on: boolean) => void
}

/** Source bindings with a checkbox each; ineligible ones are disabled with the reason. */
export function CopyBindingChoices({ bindings, selected, disabled, onToggle }: CopyBindingChoicesProps) {
  if (bindings.length === 0) return null
  return (
    <fieldset className="space-y-1">
      <legend className="mb-1 text-[12px] text-[var(--muted)]">Bindings</legend>
      {bindings.map((binding) => (
        <div key={binding.bindingId} className="text-[13px]">
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              aria-label={`Copy binding ${binding.routeLabel}`}
              checked={binding.eligible && selected.has(binding.bindingId)}
              disabled={disabled || !binding.eligible}
              onChange={(event) => onToggle(binding.bindingId, event.target.checked)}
            />
            {binding.routeLabel}
          </label>
          {!binding.eligible && binding.rejection !== null && (
            <p className="ml-6 text-[12px] text-[var(--muted)]">{binding.rejection}</p>
          )}
        </div>
      ))}
    </fieldset>
  )
}
