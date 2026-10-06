import type { ReactNode } from "react"
import { Modal } from "@/shared/ui/Modal"
import { ManualEntryModal, type ManualEntryVariant } from "./ManualEntryModal"

export type { ManualQuotaDefaults } from "../model/useQuotaForm"
export type { ManualEntryVariant }

/**
 * One shared modal shell for the credit-unit grant form. The grant form stays
 * outside this component, so the operator form keeps its own state and its own
 * server-version behavior.
 */
export interface GrantShellVariant {
  mode: "grant"
  open: boolean
  providerId: string
  providerName: string
  onClose: () => void
  children: ReactNode
}

export type ManualQuotaModalProps = ManualEntryVariant | GrantShellVariant

/**
 * Reusable manual-entry and grant modal.
 *
 * `mode: "manual"` (the default) shows the native anchor form of
 * `ManualEntryModal`; `mode: "grant"` shows the same modal shell around the
 * credit-unit grant form. Each mode keeps one modal composition only.
 */
export function ManualQuotaModal(props: ManualQuotaModalProps): ReactNode {
  if (props.mode === "grant") {
    return (
      <Modal
        isOpen={props.open}
        onClose={props.onClose}
        maxWidth="md"
        title={"Grant credit units — " + props.providerName}
        subtitle="Operator credit-unit grant. The grant adds a local ceiling above the vendor balance."
      >
        {props.children}
      </Modal>
    )
  }
  return <ManualEntryModal {...props} />
}
