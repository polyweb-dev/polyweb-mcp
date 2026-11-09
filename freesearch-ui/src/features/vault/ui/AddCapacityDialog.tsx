import { useCallback, useState } from "react"
import type { FormEvent } from "react"
import { providerIdentity, providerTypeName, supportsOAuth } from "@/domains/providers"
import { createVaultKey } from "@/domains/vault"
import type { KeyPool, VaultKey, VaultProject } from "@/domains/vault"
import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { ProviderDialogTitle } from "@/shared/ui/ProviderDialogTitle"
import { KeyFormFields } from "./KeyFormFields"
import { keySaveError } from "./keySaveError"
import { PoolCapacityDialog } from "./PoolCapacityDialog"
import { VaultOAuthDialog } from "./VaultOAuthDialog"

function keyStepCopy(provider: string, projects: readonly VaultProject[]): string {
  const target = projects.length === 1 ? ` for ${projects[0]?.name}` : " for a project"
  return `You have no ${providerTypeName(provider)} key yet. Add one, then create the pool${target}`
}

export function AddCapacityDialog({ item, provider, pool, projects, project, onClose, onSaved }: {
  item?: VaultKey
  provider?: string
  pool?: KeyPool
  projects: readonly VaultProject[]
  project?: VaultProject
  onClose: () => void
  onSaved: () => void
}) {
  const [key, setKey] = useState(item)
  const [oauthKey, setOAuthKey] = useState<VaultKey>()
  const [connecting, setConnecting] = useState(false)
  const [label, setLabel] = useState(`${providerTypeName(provider ?? "")} key`)
  const [secret, setSecret] = useState("")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const connected = useCallback(() => {
    setKey(oauthKey)
    setConnecting(false)
  }, [oauthKey])
  if (key) return <PoolCapacityDialog item={key} pool={pool} projects={projects} project={project} onClose={onClose} onSaved={onSaved} />
  if (!provider) return null
  if (connecting && oauthKey) return <VaultOAuthDialog keyId={oauthKey.id} onClose={() => setConnecting(false)} onConnected={connected} />
  const oauth = supportsOAuth(provider)
  async function addKey(event: FormEvent) {
    event.preventDefault()
    setSubmitted(true)
    if (!provider || !label.trim() || (!oauth && !secret.trim())) return
    if (oauthKey) {
      setConnecting(true)
      return
    }
    setPending(true)
    setError(null)
    try {
      const created = await createVaultKey({ provider_type: provider, label: label.trim(),
        auth_mode: oauth ? "oauth" : "api_key", ...(oauth ? {} : { secret }), overcommit: true, contention_mode: "equal" })
      if (oauth) {
        setOAuthKey(created)
        setConnecting(true)
      } else setKey(created)
    } catch (err) {
      setError(keySaveError("add", err))
    } finally {
      setSecret("")
      setSubmitted(false)
      setPending(false)
    }
  }
  return <Modal isOpen onClose={onClose} title={<ProviderDialogTitle providerId={providerIdentity(provider).id} providerName={providerTypeName(provider)} action="Add key" />} maxWidth="lg">
    <form onSubmit={(event) => void addKey(event)} className="space-y-4">
      <p>{keyStepCopy(provider, projects)}</p>
      <KeyFormFields idPrefix="capacity-key" label={label} setLabel={setLabel} secret={secret} setSecret={setSecret}
        submitted={submitted} showSecret={!oauth} />
      {error && <p role="alert" className="fs-field-error">{error}</p>}
      <FormActions><Button type="button" variant="outline" size="form" onClick={onClose}>Cancel</Button>
        <Button type="submit" size="form" disabled={pending}>{oauth ? "Connect" : "Add key"}</Button></FormActions>
    </form>
  </Modal>
}
