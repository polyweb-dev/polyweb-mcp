import { useState } from "react"
import { parseList } from "../model/settingsDraft"
import { SETTING_FIELD_CLASS } from "./settingControlStyles"

interface ListSettingControlProps {
  id: string
  label: string
  value: readonly string[]
  disabled: boolean
  onChange: (value: string[]) => void
}

/** Comma-separated list input (preferred providers, in order). */
export function ListSettingControl({ id, label, value, disabled, onChange }: ListSettingControlProps) {
  const [text, setText] = useState(value.join(", "))
  return (
    <input
      id={id}
      aria-label={label}
      value={text}
      disabled={disabled}
      placeholder="tavily, exa"
      className={SETTING_FIELD_CLASS}
      onChange={(event) => {
        setText(event.target.value)
        onChange(parseList(event.target.value))
      }}
    />
  )
}
