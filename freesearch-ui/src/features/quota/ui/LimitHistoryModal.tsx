import type { ReactNode } from "react"
import { Modal } from "@/shared/ui/Modal"
import { ProviderDialogTitle } from "@/shared/ui/ProviderDialogTitle"
import { HISTORY_ACTION } from "../model/quotaLabels"
import { LimitHistory, type LimitHistoryProps } from "./LimitHistory"

export type LimitHistoryModalProps = LimitHistoryProps & {
  open: boolean
  providerId: string
  onClose: () => void
}

const SUBTITLE = "Recorded balance changes, newest first"

/** The paged balance history of one provider, shown in a modal. */
export function LimitHistoryModal(props: LimitHistoryModalProps): ReactNode {
  const { open, onClose, providerId, providerName, ...historyProps } = props
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={<ProviderDialogTitle providerId={providerId} providerName={providerName} action={HISTORY_ACTION} />}
      subtitle={SUBTITLE}
      maxWidth={props.events.length === 0 ? "md" : "2xl"}
    >
      <LimitHistory providerName={providerName} {...historyProps} />
    </Modal>
  )
}
