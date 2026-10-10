import type { ReactNode } from "react"
import { Modal } from "@/shared/ui/Modal"
import { LimitHistory, type LimitHistoryProps } from "./LimitHistory"

export type LimitHistoryModalProps = LimitHistoryProps & {
  open: boolean
  onClose: () => void
}

const SUBTITLE = "Recorded balance changes of this provider rail, newest first."

/** The paged balance history of one provider rail, shown in a modal. */
export function LimitHistoryModal(props: LimitHistoryModalProps): ReactNode {
  const { open, onClose, providerName, ...historyProps } = props
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={"Balance history — " + providerName}
      subtitle={SUBTITLE}
      maxWidth="4xl"
    >
      <LimitHistory providerName={providerName} {...historyProps} />
    </Modal>
  )
}
