import { useId } from "react"
import { Checkbox as CheckboxPrimitive } from "@base-ui/react/checkbox"
import { Check } from "lucide-react"
import { cn } from "cn"

export interface CheckboxProps {
  id?: string
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  description?: string
  disabled?: boolean
}

/**
 * The one checkbox: a 16px box in the control style with the label beside it.
 * Use it for independent choices in a list (operations, scopes); use Switch
 * for a setting that takes effect on its own.
 */
export function Checkbox({ id, checked, onChange, label, description, disabled = false }: CheckboxProps) {
  const generatedId = useId()
  const boxId = id ?? generatedId
  return (
    <div className={cn("inline-flex items-start gap-2", disabled && "opacity-50")}>
      <CheckboxPrimitive.Root
        id={boxId}
        checked={checked}
        disabled={disabled}
        onCheckedChange={(next) => onChange(next)}
        nativeButton
        render={<button type="button" />}
        className={cn(
          "mt-0.5 grid size-4 shrink-0 place-items-center rounded-[4px] border transition-colors outline-none",
          "focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40",
          checked
            ? "border-transparent bg-[var(--signal)] text-white"
            : "border-[var(--border-subtle)] bg-[var(--surface)] hover:border-[var(--muted)]"
        )}
      >
        <CheckboxPrimitive.Indicator>
          <Check aria-hidden="true" className="size-3" strokeWidth={3} />
        </CheckboxPrimitive.Indicator>
      </CheckboxPrimitive.Root>
      <label htmlFor={boxId} className={cn("flex flex-col text-[13px] leading-5", !disabled && "cursor-pointer")}>
        <span className="text-[var(--text-strong)]">{label}</span>
        {description && <span className="text-[12px] leading-4 text-[var(--muted)]">{description}</span>}
      </label>
    </div>
  )
}
