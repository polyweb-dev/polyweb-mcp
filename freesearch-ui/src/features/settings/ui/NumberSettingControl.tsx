import { useState } from "react"
import { SETTING_FIELD_CLASS } from "./settingControlStyles"

interface NumberSettingControlProps {
  id: string
  label: string
  value: number | null
  bounds: { min: number; max: number; step: number; integer: boolean }
  disabled: boolean
  onChange: (value: number) => void
}

function parseInBounds(text: string, bounds: NumberSettingControlProps["bounds"]): number | null {
  if (text.trim() === "") return null
  const value = Number(text)
  if (!Number.isFinite(value) || (bounds.integer && !Number.isInteger(value))) return null
  return value >= bounds.min && value <= bounds.max ? value : null
}

/**
 * Number input of one field. Only a value inside the bounds (the system
 * limit caps the maximum) reaches the draft; anything else is marked invalid.
 */
export function NumberSettingControl({ id, label, value, bounds, disabled, onChange }: NumberSettingControlProps) {
  const [text, setText] = useState(value === null ? "" : String(value))
  const invalid = parseInBounds(text, bounds) === null
  return (
    <input
      id={id}
      aria-label={label}
      type="number"
      min={bounds.min}
      max={bounds.max}
      step={bounds.step}
      value={text}
      disabled={disabled}
      aria-invalid={invalid}
      className={SETTING_FIELD_CLASS}
      onChange={(event) => {
        setText(event.target.value)
        const next = parseInBounds(event.target.value, bounds)
        if (next !== null) onChange(next)
      }}
    />
  )
}
