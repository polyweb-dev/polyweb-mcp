import React from "react"
import { Tabs } from "@/components/ui/tabs"
import { PillTabsContext } from "./PillTabsContext"
import type { PillTabOption } from "./PillTabsContext"

export interface PillTabsProps {
  options: readonly PillTabOption[]
  ariaLabel: string
  idPrefix: string
  value?: string
  defaultValue?: string
  onValueChange?: (value: string) => void
  className?: string
  children: React.ReactNode
}

/**
 * Shared view-switcher root. Supports both controlled (`value`) and
 * uncontrolled (`defaultValue`) selection while Base UI owns tab interaction.
 */
export function PillTabs({
  options,
  ariaLabel,
  idPrefix,
  children,
  ...rootProps
}: PillTabsProps) {
  return (
    <PillTabsContext.Provider value={{ options, ariaLabel, idPrefix }}>
      <Tabs {...rootProps}>{children}</Tabs>
    </PillTabsContext.Provider>
  )
}

// The barrel re-exports the shared hook and context for compatibility.
// eslint-disable-next-line react-refresh/only-export-components
export { PillTabsContext, usePillTabs, type PillTabOption } from "./PillTabsContext"
export { PillTabsList } from "./PillTabsList"
export {
  PillTabsPanel,
  type PillTabsPanelProps,
} from "./PillTabsPanel"
