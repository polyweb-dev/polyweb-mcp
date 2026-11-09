import { useState } from "react"
import { providerIdentity, providerTypeName } from "@/domains/providers"
import { assignKeyPool, copyKeyPool } from "@/domains/vault"
import type { KeyPool, VaultKey, VaultProject } from "@/domains/vault"
import { Button } from "@/shared/ui/button"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { ProviderDialogTitle } from "@/shared/ui/ProviderDialogTitle"
import { Select } from "@/shared/ui/select"
import { TextField } from "@/shared/ui/TextField"

function cannotSave(mode: "copy" | "assign", pending: boolean, projectId: string, name: string) {
  return pending || !projectId || (mode === "copy" && !name.trim())
}

export function PoolProjectDialog({ mode, item, pool, projects, onClose, onSaved }: {
  mode: "copy" | "assign"
  item: VaultKey
  pool: KeyPool
  projects: VaultProject[]
  onClose: () => void
  onSaved: () => void
}) {
  const eligible = projects.filter((project) => project.available_providers.includes(item.provider_type))
  const [projectId, setProjectId] = useState(eligible[0]?.id ?? "")
  const [label, setLabel] = useState("")
  const name = label || eligible.find((project) => project.id === projectId)?.name || ""
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function save() {
    setPending(true)
    setError(null)
    try {
      if (mode === "copy") await copyKeyPool(pool.id, projectId, name.trim())
      else await assignKeyPool(pool.id, projectId)
      onSaved()
    } catch {
      setError("The pool did not save. Try again")
    } finally {
      setPending(false)
    }
  }
  return <Modal isOpen onClose={onClose} title={<ProviderDialogTitle providerId={providerIdentity(item.provider_type).id} providerName={providerTypeName(item.provider_type)} action={mode === "copy" ? "Copy pool" : "Assign pool"} />} maxWidth="md">
    <div className="space-y-4">
      <Field id="pool-target" label={mode === "copy" ? "Copy to project" : "Project"} hint="Only projects where you are the provider owner">
        <Select id="pool-target" value={projectId} onValueChange={(value) => { setProjectId(value); setLabel("") }}
          options={eligible.map((project) => ({ value: project.id, label: project.name }))} placeholder="No available projects" />
      </Field>
      {eligible.length === 0 && <p>You are not the provider owner of a project without {providerTypeName(item.provider_type)}</p>}
      {mode === "copy" && <><TextField id="copy-label" label="Pool name" type="text" value={name} onChange={setLabel} /><p>The copy has the same limits and uses the same key</p></>}
      {error && <p role="alert" className="fs-field-error">{error}</p>}
      <FormActions><Button size="form" variant="outline" onClick={onClose}>Cancel</Button><Button size="form" disabled={cannotSave(mode, pending, projectId, name)} onClick={() => void save()}>{mode === "copy" ? "Copy pool" : "Assign to project"}</Button></FormActions>
    </div>
  </Modal>
}
