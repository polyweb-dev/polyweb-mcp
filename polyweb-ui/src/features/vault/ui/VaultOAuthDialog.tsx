import { useEffect, useState } from "react"
import { Copy, ExternalLink, LoaderCircle } from "lucide-react"
import { pollVaultOAuth, startVaultOAuth } from "@/domains/vault"
import type { VaultOAuthDevice } from "@/domains/vault"
import { useClipboard } from "@/shared/clipboard/useClipboard"
import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"

export function VaultOAuthDialog({ keyId, onClose, onConnected }: {
  keyId: string
  onClose: () => void
  onConnected: () => void
}) {
  const [device, setDevice] = useState<VaultOAuthDevice | null>(null)
  const [status, setStatus] = useState("Connect to Parallel")
  const [copyError, setCopyError] = useState(false)
  const clipboard = useClipboard()

  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    let deadline = 0
    const poll = async (current: VaultOAuthDevice) => {
      if (Date.now() >= deadline) {
        setStatus("The code expired. Cancel and connect again")
        return
      }
      try {
        const result = await pollVaultOAuth(keyId, controller.signal)
        if (controller.signal.aborted) return
        if (result.status === "pending") {
          timer = window.setTimeout(() => void poll(current), (result.interval ?? current.interval) * 1000)
        } else {
          setStatus(result.status === "connected" ? "Connected" : "The connection did not complete")
          if (result.status === "connected") onConnected()
        }
      } catch {
        if (!controller.signal.aborted) setStatus("Cannot check the connection")
      }
    }
    startVaultOAuth(keyId, controller.signal).then((current) => {
      if (controller.signal.aborted) return
      setDevice(current)
      setStatus("Waiting for approval")
      deadline = Date.now() + current.expires_in * 1000
      timer = window.setTimeout(() => void poll(current), current.interval * 1000)
    }, () => {
      if (!controller.signal.aborted) setStatus("Cannot connect to Parallel")
    })
    return () => {
      controller.abort()
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [keyId, onConnected])

  return <Modal isOpen onClose={onClose} title={<><ProviderLogo providerId="parallel" name="Parallel" />Connect Parallel</>} maxWidth="md">
    {device && <ol className="list-decimal space-y-4 pl-5 marker:text-[var(--muted)]">
      <li className="pl-1">Copy this code
        <div className="mt-2 flex items-center gap-3">
          <code className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-lg">{device.user_code}</code>
          <Button type="button" size="form" variant="outline" onClick={() => void clipboard.copy(device.user_code).then((ok) => setCopyError(!ok))}>
            <Copy aria-hidden="true" className="size-4" />{clipboard.copied ? "Copied" : "Copy"}
          </Button>
        </div>
        {copyError && <p role="alert" className="fs-field-error">Cannot copy the code. Select and copy it</p>}
      </li>
      <li className="pl-1"><a className="fs-link" href={device.verification_uri} target="_blank" rel="noopener noreferrer">Open the Parallel verification page <ExternalLink aria-hidden="true" className="inline size-3" /></a> and approve</li>
    </ol>}
    <p role="status" className="mt-4 flex items-center gap-2">
      {status === "Waiting for approval" && <LoaderCircle aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />}{status}
    </p>
    <FormActions><Button size="form" variant="outline" onClick={onClose}>Cancel</Button></FormActions>
  </Modal>
}
