import type { ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/shared/ui/tooltip"
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
  onSync: () => void
  onOpenModal: (modal: CardModal) => void
  /** The detail disclosure left the card. The info control owns the detail now. */
  expanded?: boolean
  /** The panel id of the earlier disclosure; the card mounts no panel now. */
  panelId?: string
  /** The toggle of the earlier disclosure; the card mounts no panel now. */
  onToggleExpanded?: () => void
}

const ACTION = "px-3"
const TOOLTIP_DELAY = 200

/** One accessible name that states the named control and its meaning. */
function actionName(label: string, note: string, providerName: string): string {
  return label + " for " + providerName + ". " + note
}

interface DialogAction {
  label: string
  note: string
  testId: string
  onOpen: () => void
}

/**
 * One dialog action: the button shows its label only, and its one-sentence
 * meaning sits in the hover tooltip and in the accessible name.
 */
function dialogAction(input: DialogAction, providerName: string): ReactNode {
  return (
    <Tooltip key={input.testId}>
      <TooltipTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="lg"
            className={ACTION}
            data-testid={input.testId}
            aria-label={actionName(input.label, input.note, providerName)}
            onClick={input.onOpen}
          />
        }
      >
        {input.label}
      </TooltipTrigger>
      <TooltipContent>{input.note}</TooltipContent>
    </Tooltip>
  )
}

/**
 * The header controls of one card: sync, the provider balance dialog, the
 * budget limit dialog, and the history dialog.
 *
 * Each dialog action carries its one-sentence meaning as a hover tooltip and as
 * accessible text, so a screen reader states the difference between a provider
 * balance and a budget limit. The card holds no detail disclosure, because the
 * info control of the card owns the detail.
 */
export function ProviderCardActions(input: ProviderCardActionsProps): ReactNode {
  const { providerId, providerName, manualEligible, syncing } = input
  const actions: DialogAction[] = []
  if (manualEligible) {
    actions.push({
      label: BALANCE_ENTRY,
      note: BALANCE_ENTRY_NOTE,
      testId: "manual-quota-open-" + providerId,
      onOpen: () => input.onOpenModal("manual"),
    })
  }
  actions.push({
    label: SPEND_CAP,
    note: SPEND_CAP_NOTE,
    testId: "crd-grant-open-" + providerId,
    onOpen: () => input.onOpenModal("grant"),
  })
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button type="button" variant="outline" size="lg" className={ACTION}
        disabled={syncing} aria-label={"Sync limits for " + providerName} onClick={input.onSync}>
        {syncing ? "Syncing…" : "Sync"}
      </Button>
      <TooltipProvider delay={TOOLTIP_DELAY}>
        {actions.map((action) => dialogAction(action, providerName))}
      </TooltipProvider>
      <Button type="button" variant="outline" size="lg" className={ACTION}
        data-testid={"limit-history-open-" + providerId}
        aria-label={"Balance history for " + providerName}
        onClick={() => input.onOpenModal("history")}>
        History
      </Button>
    </div>
  )
}
