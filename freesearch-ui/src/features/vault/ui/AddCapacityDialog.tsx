import { useCallback, useState } from "react"
import type { FormEvent } from "react"
import { providerIdentity, providerTypeName, supportsOAuth } from "@/domains/providers"
import { createVaultKey } from "@/domains/vault"
import type { KeyPool, VaultKey, VaultProject } from "@/domains/vault"
import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { SecretInput } from "@/shared/ui/SecretInput"
import { TextField } from "@/shared/ui/TextField"
import { PoolCapacityDialog } from "./PoolCapacityDialog"
import { VaultOAuthDialog } from "./VaultOAuthDialog"

function keyStepCopy(provider: string, projects: readonly VaultProject[]): string {
  const target = projects.length === 1 ? ` for ${projects[0]?.name}` : " for a project"
  return `You have no ${providerTypeName(provider)} key yet. Add one, then create the pool${target}`
}

function fieldError(submitted: boolean, value: string, message: string): string | null {
  return submitted && !value.trim() ? message : null
}

export function AddCapacityDialog({ item, provider, pool, projects, onClose, onSaved }: {
  item?: VaultKey
  provider?: string
  pool?: KeyPool
  projects: readonly VaultProject[]
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
  if (key) return <PoolCapacityDialog item={key} pool={pool} projects={projects} onClose={onClose} onSaved={onSaved} />
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
    } catch {
      setError("The key did not save. Check the label and try again.")
    } finally {
      setSecret("")
      setSubmitted(false)
      setPending(false)
    }
  }
  return <Modal isOpen onClose={onClose} title="Add key" maxWidth="lg">
    <form onSubmit={(event) => void addKey(event)} className="space-y-4">
      <ProviderBadge providerId={providerIdentity(provider).id} name={providerTypeName(provider)} />
      <p>{keyStepCopy(provider, projects)}</p>
      <TextField id="capacity-key-label" label="Label" type="text" value={label} onChange={setLabel} error={fieldError(submitted, label, "Enter a label")} />
      {!oauth && <SecretInput id="capacity-key-secret" label="API key" value={secret} onChange={setSecret} error={fieldError(submitted, secret, "Enter the API key")} />}
      {error && <p role="alert" className="fs-field-error">{error}</p>}
      <FormActions><Button type="button" variant="outline" size="form" onClick={onClose}>Cancel</Button>
        <Button type="submit" size="form" disabled={pending}>{oauth ? "Connect" : "Add key"}</Button></FormActions>
    </form>
  </Modal>
}
