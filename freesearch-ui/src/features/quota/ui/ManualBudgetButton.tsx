import { Button } from "@/components/ui/button"

export interface ManualBudgetButtonProps {
  providerId: string
  providerName: string
  label: string
  onOpen: () => void
}

/** Opens the manual billing window for one provider row. */
export function ManualBudgetButton({ providerId, providerName, label, onOpen }: ManualBudgetButtonProps) {
  return (
    <Button
      type="button"
      variant="outline"
      size="lg"
      className="px-3"
      data-testid={"manual-quota-open-" + providerId}
      aria-label={label + " for " + providerName}
      onClick={onOpen}
    >
      {label}
    </Button>
  )
}
