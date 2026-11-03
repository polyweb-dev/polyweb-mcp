import { Modal } from "@/shared/ui/Modal"
import type { CredentialActions } from "../model/useCredentialActions"
import { ConfirmDialog } from "./ConfirmDialog"
import { CredentialForm } from "./CredentialForm"
import { OAuthConnectDialog } from "./OAuthConnectDialog"
import { RotateCredentialForm } from "./RotateCredentialForm"

interface CredentialDialogsProps {
  actions: CredentialActions
  addTitle: string
  providerTypes: readonly string[]
  /** Reload after an OAuth grant connects. */
  onConnected: () => void
}

/** Add, rotate, delete and Connect dialogs of one credential list. */
export function CredentialDialogs({ actions, addTitle, providerTypes, onConnected }: CredentialDialogsProps) {
  const { pending } = actions.status
  return (
    <>
      <Modal isOpen={actions.adding} onClose={() => actions.openAdd(false)} title={addTitle} maxWidth="md">
        {actions.adding && (
          <CredentialForm
            idPrefix="add-credential"
            providerTypes={providerTypes}
            pending={pending}
            error={actions.formError}
            onSubmit={actions.create}
            onCancel={() => actions.openAdd(false)}
          />
        )}
      </Modal>
      <Modal
        isOpen={actions.rotating !== null}
        onClose={() => actions.openRotate(null)}
        title={actions.rotating === null ? "Rotate key" : `Rotate ${actions.rotating.label}`}
        maxWidth="md"
      >
        {actions.rotating !== null && (
          <RotateCredentialForm
            key={actions.rotating.id}
            pending={pending}
            error={actions.formError}
            onSubmit={actions.rotate}
            onCancel={() => actions.openRotate(null)}
          />
        )}
      </Modal>
      <ConfirmDialog
        open={actions.deleting !== null}
        title={actions.deleting === null ? "Delete key" : `Delete ${actions.deleting.label}`}
        message="Routes that use this key stop working. This cannot be undone."
        confirmLabel="Delete key"
        pending={pending}
        onConfirm={() => void actions.confirmDelete()}
        onClose={() => actions.requestDelete(null)}
      />
      <OAuthConnectDialog
        base={actions.connectBase}
        onClose={() => actions.openConnect(null)}
        onConnected={onConnected}
      />
    </>
  )
}
