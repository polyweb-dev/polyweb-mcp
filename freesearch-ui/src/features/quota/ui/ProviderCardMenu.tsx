import type { ReactNode } from "react"
import { RowActionsMenu, type RowAction } from "@/shared/ui/RowActionsMenu"
import { BALANCE_ENTRY_ACTION, HISTORY_ACTION, SPEND_CAP } from "../model/quotaLabels"

/** The one dialog a card can hold open. */
export type CardModal = "manual" | "grant" | "history" | null

export interface ProviderCardMenuProps {
  providerName: string
  /** The provider may hold a manual balance entry, so the menu offers it. */
  manualEligible: boolean
  budgetAllowed?: boolean
  onOpenModal: (modal: CardModal) => void
}

/**
 * The `…` menu of one provider card: set balance (when the provider accepts
 * one), budget limit, and balance history. Every dialog of the card stays one
 * click away without a row of buttons on each card.
 */
export function ProviderCardMenu({ providerName, manualEligible, budgetAllowed = true, onOpenModal }: ProviderCardMenuProps): ReactNode {
  const actions: RowAction[] = []
  if (manualEligible) {
    actions.push({ key: "manual", label: BALANCE_ENTRY_ACTION, onSelect: () => onOpenModal("manual") })
  }
  if (budgetAllowed) actions.push({ key: "grant", label: SPEND_CAP, onSelect: () => onOpenModal("grant") })
  actions.push({ key: "history", label: HISTORY_ACTION, onSelect: () => onOpenModal("history") })
  return <RowActionsMenu label={"Actions for " + providerName} actions={actions} />
}
