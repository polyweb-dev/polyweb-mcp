import type { ReactNode } from "react"
import { Modal } from "@/shared/ui/Modal"
import { SPEND_CAP, SPEND_CAP_NOTE } from "../model/quotaLabels"
import { ManualEntryModal, type ManualEntryVariant } from "./ManualEntryModal"

export type { ManualQuotaDefaults } from "../model/useQuotaForm"
export type { ManualEntryVariant }

/**
 * One shared modal shell for the spend cap form. The form stays outside this
 * component, so the operator form keeps its own state and its own
 * server-version behavior.
 */
export interface SpendCapShellVariant {
  mode: "grant"
  open: boolean
  providerId: string
  providerName: string
  onClose: () => void
  children: ReactNode
}

export type ManualQuotaModalProps = ManualEntryVariant | SpendCapShellVariant

/**
 * Reusable balance-entry and spend-cap modal.
 *
 * `mode: "manual"` (the default) shows the native anchor form of
 * `ManualEntryModal`; `mode: "grant"` shows the same modal shell around the
 * spend cap form. Each mode keeps one modal composition only, and each mode
 * states its own meaning as the one visible dialog description.
 */
export function ManualQuotaModal(props: ManualQuotaModalProps): ReactNode {
  if (props.mode === "grant") {
    return (
      <Modal
        isOpen={props.open}
        onClose={props.onClose}
        maxWidth="md"
        title={SPEND_CAP + " — " + props.providerName}
        subtitle={SPEND_CAP_NOTE}
      >
        {props.children}
      </Modal>
    )
  }
  return <ManualEntryModal {...props} />
}
