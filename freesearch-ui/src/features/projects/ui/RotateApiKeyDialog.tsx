import { Modal } from "@/shared/ui/Modal"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { RotateApiKeyForm } from "./RotateApiKeyForm"

/**
 * Rotate dialog of one active key.
 *
 * The default overlap keeps the old key valid for 24 hours; "Keep current"
 * omits `expires_at`. A success closes this dialog and opens the
 * one-time reveal of the new key; a failure shows inside the dialog.
 */
export function RotateApiKeyDialog({ controller }: { controller: ProjectApiKeysController }) {
  const apiKey = controller.rotatingKey
  return (
    <Modal
      isOpen={apiKey !== null}
      onClose={() => controller.openRotate(null)}
      title={apiKey === null ? "Rotate key" : `Rotate ${apiKey.label}`}
      maxWidth="md"
    >
      {apiKey !== null && <RotateApiKeyForm key={apiKey.id} apiKey={apiKey} controller={controller} />}
    </Modal>
  )
}
