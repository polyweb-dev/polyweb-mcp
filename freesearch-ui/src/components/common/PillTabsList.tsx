import { TabsList, TabsTrigger } from "@/components/ui/tabs"
import { usePillTabs } from "./PillTabsContext"

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
