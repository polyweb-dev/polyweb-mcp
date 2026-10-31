import { Button } from "@/shared/ui/button"
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
 * The key shows in a read-only field with Copy and a "shown only once"
 * warning. Done, Escape and the close control all clear it through `onDone`;
 * nothing here stores, logs or announces the value.
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
        <div className="space-y-4">
          <p className="text-[13px] font-medium text-[var(--status-warning)]">
            This key is shown only once.
          </p>
          <p className="text-[13px] text-[var(--muted)]">
            Store it in a secret manager now. You cannot view it again after you close this dialog.
          </p>
          <div>
            <label htmlFor="api-key-reveal" className="mb-1 block text-[12px] text-[var(--muted)]">
              API key
            </label>
            <input
              id="api-key-reveal"
              type="text"
              readOnly
              value={rawKey}
              autoComplete="off"
              spellCheck={false}
              onFocus={(event) => event.currentTarget.select()}
              className="w-full rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1.5 font-mono text-[13px] text-[var(--text)] outline-none focus-visible:border-[var(--signal)]"
            />
          </div>
          {copied && (
            <p role="status" className="text-[12px] text-[var(--muted)]">
              Copied to the clipboard.
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => void copy(rawKey)}>
              Copy key
            </Button>
            <Button type="button" onClick={done}>
              Done
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
