import { ClaimProviderOwnership } from "@/domains/projects"
import type { ProviderOwner } from "@/domains/projects"
import { ApiError } from "@/shared/api/http"
import { identityDetailLabel, identityLabel } from "@/shared/lib/identity"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { LinkButton } from "@/shared/ui/LinkButton"

interface Props {
  owner: ScopedResource<ProviderOwner | null>
  projectId: string
  accountId: string
  isAdmin: boolean
  canConfigure: boolean
  onClaimed: () => void
}

function renderOwnerDetails({ current, projectId, accountId, isAdmin, canConfigure, onClaimed }: {
  current: ProviderOwner | null
  projectId: string
  accountId: string
  isAdmin: boolean
  canConfigure: boolean
  onClaimed: () => void
}) {
  const isOwner = current?.user_id === accountId
  if (current === null) return renderUnassignedOwner({ projectId, accountId, isAdmin, canClaimed: onClaimed })
  return renderAssignedOwner({ current, projectId, isAdmin, canConfigure, isOwner: isOwner === true })
}

function renderUnassignedOwner({ projectId, accountId, isAdmin, canClaimed }: {
  projectId: string
  accountId: string
  isAdmin: boolean
  canClaimed: () => void
}) {
  return <><p role="note">Provider owner: —</p>
    <p>This project has no provider owner{!isAdmin && ". Ask a project admin"}</p>
    {isAdmin && <ClaimProviderOwnership projectId={projectId} accountId={accountId} onClaimed={canClaimed} />}</>
}

function renderAssignedOwner({ current, projectId, isAdmin, canConfigure, isOwner }: {
  current: ProviderOwner
  projectId: string
  isAdmin: boolean
  canConfigure: boolean
  isOwner: boolean
}) {
  const ownerLabel = identityLabel(current)
  const ownerDetail = identityDetailLabel(current)
  const canTransfer = isAdmin
  const needsAdminHelp = !isOwner && !isAdmin && !canConfigure
  return <>
    <p role="note" title={ownerLabel === current.email ? undefined : ownerDetail}>Provider owner: {ownerLabel}{isOwner && " (you)"}
      {canTransfer && <LinkButton className="ml-2" to={`/p/${encodeURIComponent(projectId)}/members`}>Transfer ownership</LinkButton>}
      {needsAdminHelp && <span className="ml-2 text-[var(--muted)]">Ask a project admin to change this</span>}
    </p>
    {!isOwner && isAdmin && <p>Only the provider owner can add or remove capacity. Ask {ownerDetail}</p>}
  </>
}

export function ProviderOwnerLine({ owner, projectId, accountId, isAdmin, canConfigure, onClaimed }: Props) {
  if (owner.status === "loading") return <p role="status">Loading provider owner…</p>
  if (owner.status === "error") return <p role="alert">{owner.error instanceof ApiError && owner.error.status === 404
    ? "Provider ownership is not available yet" : "The provider owner could not be loaded"} <button className="underline" onClick={() => void owner.reload()}>Retry</button></p>
  return <div className="space-y-2 text-[13px]">
    {renderOwnerDetails({ current: owner.data, projectId, accountId, isAdmin, canConfigure, onClaimed })}
  </div>
}
