import { useEffect, useRef, useState } from "react"
import { SETTING_FIELD_CLASS } from "./settingControlStyles"

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

/** Hide the native spinner arrows; the value is typed. */
const NO_SPINNER =
  "[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"

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
  const errorId = `${id}-error`
  const report = useRef(onValidity)

  useEffect(() => {
    report.current = onValidity
  })
  useEffect(() => {
    report.current?.(!invalid)
  }, [invalid])
  useEffect(() => () => report.current?.(true), [])

  return (
    <div>
      <div className="relative">
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
          aria-describedby={invalid ? errorId : undefined}
          className={`${SETTING_FIELD_CLASS} ${NO_SPINNER}${suffix === undefined ? "" : " pr-8"}`}
          onChange={(event) => {
            setText(event.target.value)
            const next = parseInBounds(event.target.value, bounds)
            if (next !== null) onChange(next)
          }}
        />
        {suffix !== undefined && (
          <span aria-hidden="true" className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-[13px] text-[var(--muted)]">
            {suffix}
          </span>
        )}
      </div>
      {invalid && (
        <p id={errorId} className="fs-field-error">
          {rangeMessage(bounds)}
        </p>
      )}
    </div>
  )
}
