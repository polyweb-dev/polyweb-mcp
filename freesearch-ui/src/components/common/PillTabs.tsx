import React, { createContext, useContext } from "react"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"

export interface PillTabOption {
  value: string
  label: string
}

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

interface PillTabsContextValue {
  options: readonly PillTabOption[]
  ariaLabel: string
  idPrefix: string
}

const PillTabsContext = createContext<PillTabsContextValue | null>(null)

function usePillTabs(): PillTabsContextValue {
  const context = useContext(PillTabsContext)
  if (!context) throw new Error("PillTabs children must be inside PillTabs")
  return context
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

/** Renders the configured options with the provider-filter pill treatment. */
export function PillTabsList({ className }: { className?: string }) {
  const { options, ariaLabel, idPrefix } = usePillTabs()

  return (
    <TabsList variant="pill" aria-label={ariaLabel} className={className}>
      {options.map(({ value, label }) => (
        <TabsTrigger
          key={value}
          value={value}
          id={`${idPrefix}-tab-${value}`}
          aria-controls={`${idPrefix}-panel-${value}`}
        >
          {label}
        </TabsTrigger>
      ))}
    </TabsList>
  )
}

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
