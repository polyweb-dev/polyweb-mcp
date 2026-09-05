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
  size?: "sm" | "default"
}

export const Switch: React.FC<SwitchProps> = ({
  id,
  checked,
  onChange,
  disabled = false,
  label,
  description,
  size = "default",
}) => {
  const generatedId = useId()
  const switchId = id || generatedId

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2.5 select-none group",
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
        size={size === "sm" ? "sm" : "default"}
      />
      {(label || description) && (
        <label
          htmlFor={switchId}
          className={cn("flex flex-col", !disabled && "cursor-pointer")}
        >
          {label && (
            <span className="text-xs font-medium text-slate-200 group-hover:text-white transition-colors">
              {label}
            </span>
          )}
          {description && (
            <span className="text-[11px] text-slate-400 leading-tight">{description}</span>
          )}
        </label>
      )}
    </div>
  )
}
