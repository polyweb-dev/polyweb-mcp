import React, { useId } from "react"
import { Switch as ShadcnSwitch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"

export interface SwitchProps {
  id?: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  label?: string
  description?: string
  /** Explicit accessible name for switches without a visible label. */
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
      <ShadcnSwitch
        id={switchId}
        checked={checked}
        onCheckedChange={(newChecked) => {
          if (!disabled) onChange(newChecked)
        }}
        disabled={disabled}
        aria-label={ariaLabel}
      />
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
            <span className="text-[13px] text-[var(--muted)] leading-snug">
              {description}
            </span>
          )}
        </label>
      )}
    </div>
  )
}
