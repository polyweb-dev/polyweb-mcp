import { useEffect, useState } from "react"
import { listProjectPools, transferProviderOwner } from "@/domains/projects"
import type { ProjectMember, ProjectPool } from "@/domains/projects"
import { providerIdentity } from "@/domains/providers"
import { ApiError } from "@/shared/api/http"
import { Button } from "@/shared/ui/button"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { Select } from "@/shared/ui/select"
import { memberDetailLabel, memberSortLabel } from "../model/memberIdentity"

interface Props {
  projectId: string
  projectName: string
  members: readonly ProjectMember[]
  ownerId: string
  initialUserId?: string
  onClose: () => void
  onSaved: () => void
}

function affectedPools(pools: ProjectPool[] | null, owner: string | undefined) {
  if (pools === null || pools.length === 0) return null
  const providers = [...new Map(pools.map((pool) => {
    const identity = providerIdentity(pool.provider_type)
    return [identity.id, identity] as const
  })).values()].sort((a, b) => a.name.localeCompare(b.name))
  return (
    <>
      <p>These providers stop until {owner} adds capacity:</p>
      <ul className="space-y-1">{providers.map((provider) => (
        <li key={provider.id}>
          <ProviderBadge providerId={provider.id} name={provider.name} />
        </li>
      ))}</ul>
    </>
  )
}

export function TransferOwnershipDialog({ projectId, projectName, members, ownerId, initialUserId, onClose, onSaved }: Props) {
  const admins = members.filter((member) => member.user_id !== ownerId && member.account_active && member.status === "active" &&
    member.role === "admin").sort((a, b) => memberSortLabel(a).localeCompare(memberSortLabel(b)))
  const [selected, setSelected] = useState(initialUserId ?? admins[0]?.user_id ?? "")
  const [pools, setPools] = useState<ProjectPool[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const recipient = admins.find((member) => member.user_id === selected)
  useEffect(() => {
    const abort = new AbortController()
    void listProjectPools(projectId, abort.signal).then(setPools).catch((failure: unknown) => {
      if (!abort.signal.aborted) setError(failure instanceof ApiError && failure.status === 404
        ? "This action is not available yet" : "The pools did not load. Try again")
    })
    return () => abort.abort()
  }, [projectId])
  const transfer = async () => {
    setPending(true)
    setError(null)
    try {
      await transferProviderOwner(projectId, selected)
      onSaved()
      onClose()
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 404 ? "This action is not available yet"
        : failure instanceof ApiError && failure.status === 409 ? "The provider owner changed. Reload and try again"
          : "The new provider owner must be an active project admin")
    } finally {
      setPending(false)
    }
  }
  return (
    <Modal isOpen onClose={onClose} title="Transfer provider ownership" maxWidth="lg">
      {admins.length === 0 ? <p>Make another member a project admin first</p> : (
        <div className="space-y-4">
          <Field id="new-provider-owner" label="New provider owner">
            <Select id="new-provider-owner" value={selected} onValueChange={setSelected}
              options={admins.map((admin) => ({ value: admin.user_id, label: memberDetailLabel(admin) }))} />
          </Field>
          <p>{recipient ? memberDetailLabel(recipient) : null} becomes the provider owner of <strong className="whitespace-nowrap">{projectName}</strong></p>
          {affectedPools(pools, recipient ? memberDetailLabel(recipient) : undefined)}
        </div>
      )}
      {error && <p role="alert" className="mt-4">{error}</p>}
      <FormActions>
        <Button variant="outline" size="form" onClick={onClose}>Cancel</Button>
        {admins.length > 0 && <Button variant="destructive" size="form" disabled={pending || !recipient || pools === null} onClick={() => void transfer()}>Transfer ownership</Button>}
      </FormActions>
    </Modal>
  )
}
