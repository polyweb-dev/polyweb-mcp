import { Modal } from "@/shared/ui/Modal"
import { Button } from "@/shared/ui/button"
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
        <div className="space-y-4">
          <OAuthConnectPanel key={base} base={base} onConnected={onConnected} />
          <div className="flex justify-end">
            <Button type="button" variant="outline" onClick={onClose}>
              Close
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
