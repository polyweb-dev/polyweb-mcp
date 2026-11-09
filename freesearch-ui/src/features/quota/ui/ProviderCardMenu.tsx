import type { ReactNode } from "react"
import { RowActionsMenu, type RowAction } from "@/shared/ui/RowActionsMenu"
import { Button } from "@/shared/ui/button"
import { BALANCE_ENTRY_ACTION, HISTORY_ACTION } from "../model/quotaLabels"

/** The one dialog a card can hold open. */
export type CardModal = "manual" | "grant" | "history" | null

export interface ProviderCardMenuProps {
  providerName: string
  /** The provider may hold a manual balance entry, so the menu offers it. */
  manualEligible: boolean
  budgetAllowed?: boolean
  historyAllowed?: boolean
  alwaysMenu?: boolean
  onOpenModal: (modal: CardModal) => void
}

/**
 * The `…` menu of one provider card: set balance (when the provider accepts
 * one), budget limit, and balance history. Every dialog of the card stays one
 * click away without a row of buttons on each card.
 */
export function ProviderCardMenu({ providerName, manualEligible, budgetAllowed = true, historyAllowed = true, alwaysMenu = false, onOpenModal }: ProviderCardMenuProps): ReactNode {
  const actions: RowAction[] = []
  if (manualEligible) {
    actions.push({ key: "manual", label: BALANCE_ENTRY_ACTION, onSelect: () => onOpenModal("manual") })
  }
  if (budgetAllowed) actions.push({ key: "grant", label: "Set budget", onSelect: () => onOpenModal("grant") })
  if (historyAllowed) actions.push({ key: "history", label: "View " + HISTORY_ACTION.toLowerCase(), onSelect: () => onOpenModal("history") })
  const onlyAction = actions[0]
  if (actions.length === 0 || onlyAction === undefined) return null
  if (actions.length === 1 && !alwaysMenu) {
    return <Button type="button" variant="outline" size="sm" onClick={onlyAction.onSelect}>{onlyAction.label}</Button>
  }
  return <RowActionsMenu label={"Actions for " + providerName} actions={actions} />
}
