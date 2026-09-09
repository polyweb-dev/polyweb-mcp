import React from "react"
import { TabsContent } from "@/components/ui/tabs"
import { usePillTabs } from "./PillTabsContext"

export interface PillTabsPanelProps {
  value: string
  className?: string
  children: React.ReactNode
}

/** Mounts the active view panel with stable two-way tab linkage. */
export function PillTabsPanel({
  value,
  className,
  children,
}: PillTabsPanelProps) {
  const { idPrefix } = usePillTabs()

  return (
    <TabsContent
      value={value}
      id={`${idPrefix}-panel-${value}`}
      aria-labelledby={`${idPrefix}-tab-${value}`}
      className={className}
    >
      {children}
    </TabsContent>
  )
}
