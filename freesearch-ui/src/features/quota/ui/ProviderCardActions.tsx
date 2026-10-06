import type { ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import {
  BALANCE_ENTRY,
  BALANCE_ENTRY_NOTE,
  SPEND_CAP,
  SPEND_CAP_NOTE,
} from "../model/quotaLabels"

/** The one dialog a card can hold open. */
export type CardModal = "manual" | "grant" | "history" | null

export interface ProviderCardActionsProps {
  providerId: string
  providerName: string
  manualEligible: boolean
  syncing: boolean
  expanded: boolean
  panelId: string
  onSync: () => void
  onOpenModal: (modal: CardModal) => void
  onToggleExpanded: () => void
}

const ACTION = "px-3"

/** One accessible name that states the named control and its meaning. */
function actionName(label: string, note: string, providerName: string): string {
  return label + " for " + providerName + ". " + note
}

/**
 * The card actions: sync, the balance entry dialog, the spend cap dialog, the
 * history dialog, and the detail disclosure.
 *
 * Each dialog action carries its one-sentence meaning as accessible text, so a
 * screen reader states the difference between a balance entry and a spend cap.
 */
export function ProviderCardActions(input: ProviderCardActionsProps): ReactNode {
  const { providerId, providerName, manualEligible, syncing, expanded, panelId } = input
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button type="button" variant="outline" size="lg" className={ACTION}
        disabled={syncing} aria-label={"Sync limits for " + providerName} onClick={input.onSync}>
        {syncing ? "Syncing…" : "Sync"}
      </Button>
      {manualEligible && (
        <Button type="button" variant="outline" size="lg" className={ACTION}
          data-testid={"manual-quota-open-" + providerId}
          aria-label={actionName(BALANCE_ENTRY, BALANCE_ENTRY_NOTE, providerName)}
          onClick={() => input.onOpenModal("manual")}>
          {BALANCE_ENTRY}
        </Button>
      )}
      <Button type="button" variant="outline" size="lg" className={ACTION}
        data-testid={"crd-grant-open-" + providerId}
        aria-label={actionName(SPEND_CAP, SPEND_CAP_NOTE, providerName)}
        onClick={() => input.onOpenModal("grant")}>
        {SPEND_CAP}
      </Button>
      <Button type="button" variant="outline" size="lg" className={ACTION}
        data-testid={"limit-history-open-" + providerId}
        aria-label={"Balance history for " + providerName}
        onClick={() => input.onOpenModal("history")}>
        History
      </Button>
      <Button type="button" variant="outline" size="lg" className={ACTION}
        aria-expanded={expanded} aria-controls={panelId} onClick={input.onToggleExpanded}>
        {expanded ? "Hide detail" : "Show detail"}
      </Button>
    </div>
  )
}
