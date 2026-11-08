import { useState } from "react"
import { transferProviderOwner } from "@/domains/projects"
import type { ProviderOwner } from "@/domains/projects"
import { ApiError } from "@/shared/api/http"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { Button } from "@/shared/ui/button"
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog"

interface Props {
  owner: ScopedResource<ProviderOwner | null>
  canManage: boolean
  projectId: string
  accountId: string
  onSaved: (message: string) => void
}

export function MembersOwnershipControls({ owner, canManage, projectId, accountId, onSaved }: Props) {
  const [claiming, setClaiming] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const claim = async () => {
    setPending(true)
    try {
      await transferProviderOwner(projectId, accountId)
      setClaiming(false)
      onSaved("Provider ownership transferred")
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 404 ? "This action is not available yet."
        : "The provider owner changed. Reload and try again.")
      setClaiming(false)
    } finally {
      setPending(false)
    }
  }
  const unavailable = owner.status === "error"
  const canClaim = canManage && owner.status === "ready" && owner.data === null
  return (
    <>
      {unavailable && <p role="status" className="mb-4 text-[var(--muted)]">Provider ownership is not available yet.</p>}
      {error && <p role="alert" className="mb-4 text-[var(--muted)]">{error}</p>}
      {canClaim && <div className="mb-4"><Button onClick={() => setClaiming(true)}>Claim provider ownership</Button></div>}
      <ConfirmDialog open={claiming} title="Claim provider ownership"
        message="You become the provider owner of this project. Add provider capacity before the calls work again."
        confirmLabel="Claim provider ownership" pending={pending} onClose={() => setClaiming(false)} onConfirm={() => void claim()} />
    </>
  )
}
