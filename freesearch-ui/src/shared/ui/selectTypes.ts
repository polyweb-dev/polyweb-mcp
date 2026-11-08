import type { ReactNode } from "react"

export interface SelectOption {
  value: string
  label: string
  /** Leading mark of the row, such as a provider logo. */
  icon?: ReactNode
  /** Muted second part of the row, such as `System key`. */
  description?: string
  disabled?: boolean
}

/** The state of one row, which tells the caller how to present its content. */
export interface SelectOptionState {
  /** The shown value of the control. */
  selected: boolean
  /** The row of the keyboard cursor. */
  active: boolean
}
