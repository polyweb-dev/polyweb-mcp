import React, { useId } from "react"
import { Switch as SwitchPrimitive } from "@base-ui/react/switch"
import { cn } from "cn"

export interface SwitchProps {
  id?: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  label?: string
  description?: string
  ariaLabel?: string
}

export const Switch: React.FC<SwitchProps> = ({
  id,
  checked,
  onChange,
  disabled = false,
  label,
  description,
  ariaLabel,
}) => {
  const generatedId = useId()
  const switchId = id || generatedId

  return (
    <div
      className={cn(
        "inline-flex items-center gap-3 select-none group",
        disabled && "cursor-not-allowed opacity-45"
      )}
    >
      <SwitchPrimitive.Root
        id={switchId}
        checked={checked}
        disabled={disabled}
        onCheckedChange={(next) => onChange(next)}
        aria-label={ariaLabel ?? label}
        nativeButton
        render={<button type="button" />}
        className={cn(
          "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border p-0.5 transition-all duration-200 ease-in-out outline-none motion-reduce:transition-none",
          "before:absolute before:-inset-2 before:content-['']",
          "focus-visible:border-[var(--signal)] focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40",
          checked
            ? "border-transparent bg-[var(--signal)]"
            : "border-[var(--border-subtle)] bg-transparent",
          "disabled:cursor-not-allowed disabled:opacity-50"
        )}
      >
        <SwitchPrimitive.Thumb
          aria-hidden="true"
          className={cn(
            "pointer-events-none block h-4 w-4 rounded-full bg-[var(--text-strong)] shadow-sm transition-transform duration-200 ease-in-out motion-reduce:transition-none",
            checked && "translate-x-[14px]"
          )}
        />
      </SwitchPrimitive.Root>
      {(label || description) && (
        <label
          htmlFor={switchId}
          className={cn("flex flex-col", !disabled && "cursor-pointer")}
        >
          {label && (
            <span className="text-[13px] font-medium text-[var(--text-strong)] group-hover:text-white transition-colors">
              {label}
            </span>
          )}
          {description && (
            <span className="text-[13px] text-[var(--muted)] leading-snug">{description}</span>
          )}
        </label>
      )}
    </div>
  )
}
