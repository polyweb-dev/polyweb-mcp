import { createContext, useContext } from "react"

export interface PillTabOption {
  value: string
  label: string
}

interface PillTabsContextValue {
  options: readonly PillTabOption[]
  ariaLabel: string
  idPrefix: string
}

export const PillTabsContext = createContext<PillTabsContextValue | null>(null)

export function usePillTabs(): PillTabsContextValue {
  const context = useContext(PillTabsContext)
  if (!context) throw new Error("PillTabs children must be inside PillTabs")
  return context
}
