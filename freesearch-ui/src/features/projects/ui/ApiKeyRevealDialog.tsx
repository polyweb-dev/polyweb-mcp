import { Copy } from "lucide-react"
import { Button } from "@/shared/ui/button"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { useClipboard } from "@/shared/clipboard/useClipboard"

export interface ApiKeyRevealDialogProps {
  /** The raw key; the dialog is open while it is present. */
  rawKey: string | null
  /** Close the dialog and clear the raw key from memory. */
  onDone: () => void
}

/**
 * One-time reveal of a newly issued or rotated key.
 *
 * The key shows in a read-only mono field with Copy beside it, under a
 * "shown only once" warning. Done, Escape and the close control all clear it
 * through `onDone`; nothing here stores, logs or announces the value.
 */
export function ApiKeyRevealDialog({ rawKey, onDone }: ApiKeyRevealDialogProps) {
  const { copied, copy, reset } = useClipboard({ resetAfterMs: 2000 })

  const done = () => {
    reset()
    onDone()
  }

  return (
    <Modal isOpen={rawKey !== null} onClose={done} title="Copy your new API key" maxWidth="lg">
      {rawKey !== null && (
        <>
          <p className="mb-4 text-[13px] text-[var(--muted)]">
            <span className="font-medium text-[var(--status-warning)]">This key is shown only once.</span>{" "}
            Store it in a secret manager before you close this dialog.
          </p>
          <Field id="api-key-reveal" label="API key">
            <div className="flex items-center gap-2">
              <input
                id="api-key-reveal"
                type="text"
                readOnly
                value={rawKey}
                autoComplete="off"
                spellCheck={false}
                onFocus={(event) => event.currentTarget.select()}
                className="fs-input min-w-0 flex-1 font-mono text-[12px]"
              />
              <Button type="button" size="form" variant="outline" onClick={() => void copy(rawKey)}>
                <Copy aria-hidden="true" />
                Copy key
              </Button>
            </div>
          </Field>
          <FormActions
            start={
              copied ? (
                <span role="status" className="text-[12px]">
                  Copied to the clipboard.
                </span>
              ) : undefined
            }
          >
            <Button type="button" size="form" onClick={done}>
              Done
            </Button>
          </FormActions>
        </>
      )}
    </Modal>
  )
}
