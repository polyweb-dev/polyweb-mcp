import type { ReactNode } from "react"
import { Tabs } from "@/shared/ui/tabs"
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
  children: ReactNode
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

export type { PillTabOption } from "./PillTabsContext"
