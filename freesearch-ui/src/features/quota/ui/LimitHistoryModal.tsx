import type { ReactNode } from "react"
import { Modal } from "@/shared/ui/Modal"
import { HISTORY_ACTION } from "../model/quotaLabels"
import { LimitHistory, type LimitHistoryProps } from "./LimitHistory"

export type LimitHistoryModalProps = LimitHistoryProps & {
  open: boolean
  onClose: () => void
}

const SUBTITLE = "Recorded balance changes, newest first"

/** The paged balance history of one provider, shown in a modal. */
export function LimitHistoryModal(props: LimitHistoryModalProps): ReactNode {
  const { open, onClose, providerName, ...historyProps } = props
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={HISTORY_ACTION + " for " + providerName}
      subtitle={SUBTITLE}
      maxWidth={props.events.length === 0 ? "md" : "2xl"}
    >
      <LimitHistory providerName={providerName} {...historyProps} />
    </Modal>
  )
}
