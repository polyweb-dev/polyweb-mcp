import { useState } from "react"
import { providerIdentity, providerTypeName } from "@/domains/providers"
import type { ProviderTypeView } from "@/domains/providers"
import { getKeyPool, listVaultKeys } from "@/domains/vault"
import type { KeyPool, VaultKey } from "@/domains/vault"
import type { ProjectPool } from "@/domains/projects"
import { AddCapacityDialog } from "@/features/vault/ui/AddCapacityDialog"
import { poolDialogTitle } from "@/features/vault/model/poolDialogTitle"
import { ApiError } from "@/shared/api/http"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { Button } from "@/shared/ui/button"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { ProviderDialogTitle } from "@/shared/ui/ProviderDialogTitle"
import { ProviderSelect } from "@/shared/ui/ProviderSelect"
import { Select } from "@/shared/ui/select"

interface Props {
  projectId: string
  projectName: string
  providers: readonly ProviderTypeView[]
  provider?: string
  pool?: ProjectPool
  onClose: () => void
  onSaved: () => void
}

interface VaultData {
  keys: VaultKey[]
  pool?: KeyPool
}

function renderCapacitySelection({ providers, pool, provider, setProvider, keys, item, setSelectedKey }: {
  providers: readonly ProviderTypeView[]
  pool?: ProjectPool
  provider: string
  setProvider: (value: string) => void
  keys: VaultKey[]
  item?: VaultKey
  setSelectedKey: (value: string) => void
}) {
  let keyField
  if (keys.length === 0) {
    keyField = <p>You have no key for {providerTypeName(pool?.provider_type ?? provider)}</p>
  } else if (pool && keys.length > 1) {
    keyField = <p>More than one key has this label. Edit this pool in Keys and pools</p>
  } else {
    keyField = <Field id="capacity-key" label="Key"><Select id="capacity-key" value={item?.id ?? ""} placeholder="Select a key"
      options={keys.map((key) => ({ value: key.id, label: key.label }))} onValueChange={setSelectedKey} /></Field>
  }
  return <div className="space-y-4">
    {!pool && <Field id="capacity-provider" label="Provider">
      <ProviderSelect id="capacity-provider" value={providerIdentity(provider).id}
        options={providers.map((entry) => ({ value: providerIdentity(entry.providerType).id, label: providerIdentity(entry.providerType).name }))}
        onValueChange={(value) => {
          const selected = providers.find((entry) => providerIdentity(entry.providerType).id === value)
          if (selected) { setProvider(selected.providerType); setSelectedKey("") }
        }} />
    </Field>}
    {keyField}
  </div>
}

function findKeys(data: VaultData | null, provider: string, pool?: ProjectPool): VaultKey[] {
  if (!data) return []
  return data.keys.filter((item) => item.provider_type === (pool?.provider_type ?? provider) &&
    (!pool || item.label === pool.key_label))
}

function renderChooser({ props, vault, provider, setProvider, keys, item, setSelectedKey, setSelected }: {
  props: Props
  vault: ScopedResource<VaultData>
  provider: string
  setProvider: (value: string) => void
  keys: VaultKey[]
  item?: VaultKey
  setSelectedKey: (value: string) => void
  setSelected: (value: boolean) => void
}) {
  const { pool, providers, onClose } = props
  const identity = providerIdentity(pool ? pool.provider_type : provider)
  return <Modal isOpen onClose={onClose} title={<ProviderDialogTitle providerId={identity.id} title={poolDialogTitle(pool ? "edit" : "capacity", identity.name)} />} maxWidth="lg">
    {vault.status === "loading" && <p role="status">Loading keys...</p>}
    {vault.status === "error" && <p role="alert">{vault.error instanceof ApiError && vault.error.status === 404
      ? "Keys and pools are not available yet" : "Cannot load Keys and pools"}</p>}
    {vault.status === "ready" && renderCapacitySelection({ providers, pool, provider, setProvider, keys, item, setSelectedKey })}
    <FormActions><Button variant="outline" size="form" onClick={onClose}>Cancel</Button>
      {!pool && (item || keys.length === 0) && provider && <Button size="form" onClick={() => setSelected(true)}>Continue</Button>}
    </FormActions>
  </Modal>
}

function shouldOpenPoolDialog(item: VaultKey | undefined, props: Props, keys: VaultKey[], selected: boolean): boolean {
  if (!item) return false
  return selected || Boolean(props.pool) || (props.provider !== undefined && keys.length === 1)
}

function shouldAddKey(props: Props, keys: VaultKey[], provider: string, selected: boolean): boolean {
  return !props.pool && keys.length === 0 && Boolean(provider) && (selected || props.provider === provider)
}

function selectedItem(keys: VaultKey[], selectedKey: string): VaultKey | undefined {
  return keys.find((key) => key.id === selectedKey) ?? (keys.length === 1 ? keys[0] : undefined)
}

export function ProjectCapacityDialog(props: Props) {
  const { projectId, projectName, providers, pool, onClose, onSaved } = props
  const [provider, setProvider] = useState(props.provider ?? providers[0]?.providerType ?? "")
  const [selectedKey, setSelectedKey] = useState("")
  const [selected, setSelected] = useState(false)
  const vault = useScopedResource<VaultData>({
    scopeKey: `${projectId}:${pool?.pool_id ?? "new"}`,
    load: async (signal) => ({
      keys: await listVaultKeys(signal),
      pool: pool ? await getKeyPool(pool.pool_id, signal) : undefined,
    }),
  })
  const keys = findKeys(vault.status === "ready" ? vault.data : null, provider, pool)
  const item = selectedItem(keys, selectedKey)
  const showPoolDialog = shouldOpenPoolDialog(item, props, keys, selected)
  if (vault.status === "ready" && shouldAddKey(props, keys, provider, selected)) {
    return <AddCapacityDialog provider={provider}
      project={{ id: projectId, name: projectName, available_providers: [provider] }}
      projects={[{ id: projectId, name: projectName, available_providers: [provider] }]}
      onClose={onClose} onSaved={onSaved} />
  }
  if (showPoolDialog && item && vault.status === "ready") {
    return <AddCapacityDialog item={item} pool={vault.data.pool}
      project={{ id: projectId, name: projectName, available_providers: [item.provider_type] }}
      projects={[{ id: projectId, name: projectName, available_providers: [item.provider_type] }]}
      onClose={onClose} onSaved={onSaved} />
  }
  return renderChooser({ props, vault, provider, setProvider, keys, item, setSelectedKey, setSelected })
}
