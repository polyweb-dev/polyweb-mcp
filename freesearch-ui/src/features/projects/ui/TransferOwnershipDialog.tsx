import { useEffect, useState } from "react"
import { listProjectPools, transferProviderOwner } from "@/domains/projects"
import type { ProjectMember, ProjectPool } from "@/domains/projects"
import { providerIdentity } from "@/domains/providers"
import { ApiError } from "@/shared/api/http"
import { Button } from "@/shared/ui/button"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import { Select } from "@/shared/ui/select"

interface Props {
  projectId: string
  projectName: string
  members: readonly ProjectMember[]
  ownerId: string
  initialUserId?: string
  onClose: () => void
  onSaved: () => void
}

function affectedPools(pools: ProjectPool[] | null, projectName: string) {
  if (pools === null || pools.length === 0) return null
  return (
    <>
      <p>These pools no longer serve {projectName}:</p>
      <ul className="space-y-1">{[...pools].sort((a, b) => a.label.localeCompare(b.label)).map((pool) => (
        <li key={pool.pool_id} className="flex items-center gap-2">
          <ProviderLogo providerId={providerIdentity(pool.provider_type).id} name={pool.provider_type} />
          {pool.label}
        </li>
      ))}</ul>
    </>
  )
}

export function TransferOwnershipDialog({ projectId, projectName, members, ownerId, initialUserId, onClose, onSaved }: Props) {
  const admins = members.filter((member) => member.user_id !== ownerId && member.status === "active" &&
    member.role === "admin").sort((a, b) => a.email.localeCompare(b.email))
  const [selected, setSelected] = useState(initialUserId ?? admins[0]?.user_id ?? "")
  const [pools, setPools] = useState<ProjectPool[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const recipient = admins.find((member) => member.user_id === selected)
  useEffect(() => {
    const abort = new AbortController()
    void listProjectPools(projectId, abort.signal).then(setPools).catch((failure: unknown) => {
      if (!abort.signal.aborted) setError(failure instanceof ApiError && failure.status === 404
        ? "This action is not available yet." : "The pools did not load. Try again.")
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
      setError(failure instanceof ApiError && failure.status === 404 ? "This action is not available yet."
        : failure instanceof ApiError && failure.status === 409 ? "The provider owner changed. Reload and try again."
          : "The new provider owner must be an active project admin.")
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
              options={admins.map((admin) => ({ value: admin.user_id, label: admin.email }))} />
          </Field>
          <p>{recipient?.email} becomes the provider owner of {projectName}</p>
          {affectedPools(pools, projectName)}
          <p>Paid providers stop until {recipient?.email} adds capacity</p>
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
