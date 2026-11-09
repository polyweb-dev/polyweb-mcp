import { useState } from "react"
import { transferProviderOwner } from "@/domains/projects"
import type { ProviderOwner } from "@/domains/projects"
import { ApiError } from "@/shared/api/http"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { Button } from "@/shared/ui/button"
import { LinkButton } from "@/shared/ui/LinkButton"
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog"

interface Props {
  owner: ScopedResource<ProviderOwner | null>
  projectId: string
  accountId: string
  isAdmin: boolean
  canConfigure: boolean
  onClaimed: () => void
}

function renderOwnerDetails({ current, projectId, accountId, isAdmin, canConfigure, claim }: {
  current: ProviderOwner | null
  projectId: string
  accountId: string
  isAdmin: boolean
  canConfigure: boolean
  claim: () => void
}) {
  const isOwner = current?.user_id === accountId
  if (!current) return <><p role="note">Provider owner: —</p>
    <p>This project has no provider owner{!isAdmin && ". Ask a project admin"}</p>
    {isAdmin && <Button size="form" onClick={claim}>Become provider owner</Button>}</>
  return <>
    <p role="note">Provider owner: {current.email}{isOwner && " (you)"}
      {isAdmin && <LinkButton className="ml-2" to={`/p/${encodeURIComponent(projectId)}/members`}>Transfer ownership</LinkButton>}
      {!isOwner && !isAdmin && !canConfigure && <span className="ml-2 text-[var(--muted)]">Ask a project admin to change this</span>}
    </p>
    {!isOwner && isAdmin && <p>Only the provider owner can add or remove capacity. Ask {current.email}</p>}
  </>
}

export function ProviderOwnerLine({ owner, projectId, accountId, isAdmin, canConfigure, onClaimed }: Props) {
  const [claiming, setClaiming] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const claim = async () => {
    setPending(true)
    setError(null)
    try {
      await transferProviderOwner(projectId, accountId)
      setClaiming(false)
      onClaimed()
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 404
        ? "Provider ownership is not available yet" : "Provider ownership could not be changed. Try again")
    } finally {
      setPending(false)
    }
  }
  if (owner.status === "loading") return <p role="status">Loading provider owner…</p>
  if (owner.status === "error") return <p role="alert">{owner.error instanceof ApiError && owner.error.status === 404
    ? "Provider ownership is not available yet" : "The provider owner could not be loaded"} <button className="underline" onClick={() => void owner.reload()}>Retry</button></p>
  return <div className="space-y-2 text-[13px]">
    {renderOwnerDetails({ current: owner.data, projectId, accountId, isAdmin, canConfigure, claim: () => setClaiming(true) })}
    {error && <p role="alert">{error}</p>}
    <ConfirmDialog open={claiming} title="Become provider owner" message="You become the provider owner of this project"
      confirmLabel="Become provider owner" pending={pending} error={error} onClose={() => setClaiming(false)} onConfirm={() => void claim()} />
  </div>
}
