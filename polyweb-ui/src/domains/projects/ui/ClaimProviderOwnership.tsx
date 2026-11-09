import { useRef, useState } from "react"
import { transferProviderOwner } from "../api/providerOwnerApi"
import { ApiError } from "@/shared/api/http"
import { Button } from "@/shared/ui/button"
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog"

interface Props {
  projectId: string
  accountId: string
  onClaimed: () => void
}

export function ClaimProviderOwnership({ projectId, accountId, onClaimed }: Props) {
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)
  const claim = async () => {
    if (inFlight.current) return
    inFlight.current = true
    setPending(true)
    setError(null)
    try {
      await transferProviderOwner(projectId, accountId)
      setOpen(false)
      onClaimed()
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 404
        ? "Provider ownership is not available yet" : "Provider ownership could not be changed. Try again")
    } finally {
      inFlight.current = false
      setPending(false)
    }
  }
  return <>
    <Button size="form" onClick={() => { setError(null); setOpen(true) }}>Claim provider ownership</Button>
    <ConfirmDialog open={open} title="Claim provider ownership" confirmLabel="Claim provider ownership"
      message="You become the provider owner of this project. Add provider capacity before calls work again"
      pending={pending} error={error} onClose={() => setOpen(false)} onConfirm={() => void claim()} />
  </>
}
