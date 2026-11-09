import type { Project } from "@/domains/projects"
import { Modal } from "@/shared/ui/Modal"
import { CopySettingsForm } from "./CopySettingsForm"
import type { CopyTarget } from "./CopySettingsForm"

interface CopySettingsDialogProps {
  open: boolean
  target: CopyTarget
  sources: readonly Project[]
  onClose: () => void
}

/** "Copy settings" dialog; its form mounts fresh on every open. */
export function CopySettingsDialog({ open, target, sources, onClose }: CopySettingsDialogProps) {
  return (
    <Modal isOpen={open} onClose={onClose} title="Copy settings" maxWidth="2xl">
      {open && <CopySettingsForm target={target} sources={sources} onClose={onClose} />}
    </Modal>
  )
}
