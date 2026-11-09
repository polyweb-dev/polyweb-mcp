import { ClaimProviderOwnership } from "@/domains/projects"
import type { ProviderOwner } from "@/domains/projects"
import type { ScopedResource } from "@/shared/lib/useScopedResource"

interface Props {
  owner: ScopedResource<ProviderOwner | null>
  canManage: boolean
  projectId: string
  accountId: string
  onSaved: (message: string) => void
}

export function MembersOwnershipControls({ owner, canManage, projectId, accountId, onSaved }: Props) {
  const unavailable = owner.status === "error"
  const canClaim = canManage && owner.status === "ready" && owner.data === null
  return (
    <>
      {unavailable && <p role="status" className="mb-4 text-[var(--muted)]">Provider ownership is not available yet</p>}
      {canClaim && <div className="mb-4"><ClaimProviderOwnership projectId={projectId} accountId={accountId}
        onClaimed={() => onSaved("Provider ownership transferred")} /></div>}
    </>
  )
}
