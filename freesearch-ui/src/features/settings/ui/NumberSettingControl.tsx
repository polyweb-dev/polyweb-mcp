import { useEffect, useRef, useState } from "react"
import { NumericField } from "@/shared/ui/NumericField"

interface NumberSettingControlProps {
  id: string
  label: string
  value: number | null
  bounds: { min: number; max: number; step: number; integer: boolean }
  disabled: boolean
  /** Unit shown inside the input, such as `%`. */
  suffix?: string
  onChange: (value: number) => void
  /** Called on mount, on every validity change, and with `true` on unmount. */
  onValidity?: (valid: boolean) => void
}

function parseInBounds(text: string, bounds: NumberSettingControlProps["bounds"]): number | null {
  if (text.trim() === "") return null
  const value = Number(text)
  if (!Number.isFinite(value) || (bounds.integer && !Number.isInteger(value))) return null
  return value >= bounds.min && value <= bounds.max ? value : null
}

/** "Enter a whole number from 1 to 90" */
function rangeMessage(bounds: NumberSettingControlProps["bounds"]): string {
  const kind = bounds.integer ? "a whole number" : "a number"
  return `Enter ${kind} from ${bounds.min.toLocaleString()} to ${bounds.max.toLocaleString()}`
}

/**
 * Number input of one field. Only a value inside the bounds (the system
 * limit caps the maximum) reaches the draft; anything else shows the allowed
 * range under the input and is reported invalid, so Save can refuse it.
 */
export function NumberSettingControl({ id, label, value, bounds, disabled, suffix, onChange, onValidity }: NumberSettingControlProps) {
  const [text, setText] = useState(value === null ? "" : String(value))
  const invalid = parseInBounds(text, bounds) === null
  const report = useRef(onValidity)

  useEffect(() => {
    report.current = onValidity
  })
  useEffect(() => {
    report.current?.(!invalid)
  }, [invalid])
  useEffect(() => () => report.current?.(true), [])

  return (
    <div className={`relative [&_label]:sr-only${suffix === undefined ? "" : " [&_input]:pr-10"}`}>
      <NumericField
        id={id}
        label={label}
        min={bounds.min}
        step={bounds.step}
        value={text}
        disabled={disabled}
        error={invalid ? rangeMessage(bounds) : undefined}
        onChange={(text) => {
          setText(text)
          const next = parseInBounds(text, bounds)
          if (next !== null) onChange(next)
        }}
      />
      {suffix !== undefined && (
        <span aria-hidden="true" className="pointer-events-none absolute top-4 right-3 -translate-y-1/2 text-[13px] text-[var(--muted)]">
          {suffix}
        </span>
      )}
    </div>
  )
}
