import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { OAuthConnectPanel } from "./OAuthConnectPanel"

interface OAuthConnectDialogProps {
  /** Credential base path of the open flow, or `null` when closed. */
  base: string | null
  onClose: () => void
  onConnected: () => void
}

/** "Connect Parallel" dialog of one OAuth credential row. */
export function OAuthConnectDialog({ base, onClose, onConnected }: OAuthConnectDialogProps) {
  return (
    <Modal isOpen={base !== null} onClose={onClose} title="Connect Parallel" maxWidth="md">
      {base !== null && (
        <>
          <OAuthConnectPanel key={base} base={base} onConnected={onConnected} />
          <FormActions>
            <Button type="button" size="form" variant="outline" onClick={onClose}>
              Close
            </Button>
          </FormActions>
        </>
      )}
    </Modal>
  )
}
