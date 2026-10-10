import { Button } from "@/shared/ui/button"

export interface ManualBudgetButtonProps {
  providerId: string
  providerName: string
  label: string
  /** One sentence of the control meaning, added to its accessible name. */
  note?: string
  onOpen: () => void
}

/** Opens the manual billing window for one provider row. */
export function ManualBudgetButton({
  providerId,
  providerName,
  label,
  note,
  onOpen,
}: ManualBudgetButtonProps) {
  const name = label + " for " + providerName + (note === undefined ? "" : ". " + note)
  return (
    <Button
      type="button"
      variant="outline"
      size="lg"
      className="px-3"
      data-testid={"manual-quota-open-" + providerId}
      aria-label={name}
      onClick={onOpen}
    >
      {label}
    </Button>
  )
}
