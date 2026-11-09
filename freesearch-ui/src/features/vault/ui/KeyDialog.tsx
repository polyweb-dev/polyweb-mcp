import { useState } from "react"
import type { FormEvent } from "react"
import { credentialProviderTypes, providerIdentity, providerTypeName, supportsOAuth } from "@/domains/providers"
import { createVaultKey, rotateVaultKey, updateVaultKey } from "@/domains/vault"
import type { VaultKey } from "@/domains/vault"
import { AdvancedSection } from "@/shared/ui/AdvancedSection"
import { Button } from "@/shared/ui/button"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { ProviderDialogTitle } from "@/shared/ui/ProviderDialogTitle"
import { ProviderSelect } from "@/shared/ui/ProviderSelect"
import { Select } from "@/shared/ui/select"
import { NumericField } from "@/shared/ui/NumericField"
import { Switch } from "@/shared/ui/Switch"
import { KeyFormFields } from "./KeyFormFields"
import { keySaveError } from "./keySaveError"

type Mode = "add" | "settings" | "rotate"

function invalidCapacity(capacity: string): boolean {
  return capacity !== "" && (!Number.isInteger(Number(capacity)) || Number(capacity) <= 0)
}

function needsSecret(mode: Mode, auth: string): boolean {
  return mode === "rotate" || (mode === "add" && auth === "api_key")
}

function capacityToSave(form: HTMLFormElement, capacity: string, initial: string): string {
  return !form.elements.namedItem("key-limit") && invalidCapacity(capacity) ? initial : capacity
}

function invalidKeyValues({ mode, auth, label, capacity, secret }: {
  mode: Mode; auth: string; label: string; capacity: string; secret: string
}): boolean {
  return (mode !== "rotate" && (!label.trim() || invalidCapacity(capacity))) || (needsSecret(mode, auth) && !secret.trim())
}

function initialKeyValues(item?: VaultKey) {
  const provider = item?.provider_type ?? credentialProviderTypes()[0] ?? ""
  return {
    provider,
    label: item?.label ?? `${providerTypeName(provider)} key`,
    overcommit: item?.overcommit ?? true,
    contention: item?.contention_mode ?? "equal",
  }
}

function initialKeyCapacity(item?: VaultKey) {
  return {
    capacity: item?.capacity?.limit?.toString() ?? "",
    windowSeconds: item?.capacity?.window_seconds ?? 60,
  }
}

const TITLES: Record<Mode, string> = { add: "Add key", rotate: "Rotate key", settings: "Edit key" }
const ACTIONS: Record<Mode, string> = { add: "Add key", rotate: "Rotate key", settings: "Save settings" }

export function KeyDialog({ mode, item, onClose, onSaved }: {
  mode: Mode
  item?: VaultKey
  onClose: () => void
  onSaved: () => void
}) {
  const initial = initialKeyValues(item)
  const initialCapacity = initialKeyCapacity(item)
  const [provider, setProvider] = useState(initial.provider)
  const [label, setLabel] = useState(initial.label)
  const [auth, setAuth] = useState("api_key")
  const [secret, setSecret] = useState("")
  const [capacity, setCapacity] = useState(initialCapacity.capacity)
  const [windowSeconds, setWindowSeconds] = useState(initialCapacity.windowSeconds)
  const [overcommit, setOvercommit] = useState(initial.overcommit)
  const [contention, setContention] = useState<"equal" | "ratio">(initial.contention)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitted(true)
    const activeCapacity = capacityToSave(event.currentTarget, capacity, initialCapacity.capacity)
    if (invalidKeyValues({ mode, auth, label, capacity: activeCapacity, secret })) return
    const policy = { label: label.trim(), capacity: activeCapacity ? { limit: Number(activeCapacity), window_seconds: windowSeconds } : null, overcommit, contention_mode: contention }
    setPending(true)
    setError(null)
    try {
      if (mode === "add") await createVaultKey({ ...policy, provider_type: provider, auth_mode: auth, ...(auth === "api_key" ? { secret } : {}) })
      else if (item && mode === "settings") await updateVaultKey(item.id, policy)
      else if (item) await rotateVaultKey(item.id, item.generation, secret)
      onSaved()
    } catch (err) {
      setError(keySaveError(mode, err))
    } finally {
      setSecret("")
      setSubmitted(false)
      setPending(false)
    }
  }

  const title = TITLES[mode]
  const action = ACTIONS[mode]
  return (
    <Modal isOpen onClose={onClose} title={mode === "add" ? title : <ProviderDialogTitle providerId={providerIdentity(provider).id} title={title} />} maxWidth="lg">
      <form noValidate onSubmit={(event) => void save(event)} className="space-y-4">
        {mode === "rotate" && <p>Enter the new API key. Each pool that uses this key switches to it at once</p>}
        {mode === "add" && (
          <Field id="vault-provider" label="Provider">
            <ProviderSelect id="vault-provider" value={providerIdentity(provider).id}
              options={credentialProviderTypes().map((type) => ({ value: providerIdentity(type).id, label: providerTypeName(type) }))}
              onValueChange={(value) => {
                const next = credentialProviderTypes().find((type) => providerIdentity(type).id === value) ?? value
                setLabel((current) => current === `${providerTypeName(provider)} key` ? `${providerTypeName(next)} key` : current)
                setProvider(next)
                setAuth("api_key")
              }} />
          </Field>
        )}
        <KeyFormFields idPrefix="vault" label={label} setLabel={setLabel} secret={secret} setSecret={setSecret}
          submitted={submitted} showLabel={mode !== "rotate"} showSecret={needsSecret(mode, auth)}>
          {mode === "add" && supportsOAuth(provider) && (
            <Field id="vault-auth" label="Authentication">
              <Select id="vault-auth" value={auth} onValueChange={setAuth}
                options={[{ value: "api_key", label: "API key" }, { value: "oauth", label: "OAuth" }]} />
            </Field>
          )}
        </KeyFormFields>
        {mode !== "rotate" && (
          <AdvancedSection label="Advanced">
            <NumericField id="key-limit" label="Key limit" min="1" value={capacity} onChange={setCapacity} error={submitted && invalidCapacity(capacity) ? "Enter a positive whole number" : undefined} hint="Enter the requests that the provider allows for this key, or leave empty if unknown" />
            <Field id="key-window" label="Rate unit">
              <Select id="key-window" value={String(windowSeconds)} onValueChange={(value) => setWindowSeconds(Number(value))}
                options={[{ value: "1", label: "Per second" }, { value: "60", label: "Per minute" }, { value: "3600", label: "Per hour" }]} />
            </Field>
            <Switch checked={overcommit} onChange={setOvercommit} label="Overcommit" description="Pool limits can exceed the key limit. A busy pool can use idle capacity from other pools" />
            <Field id="key-contention" label="When pools compete">
              <Select id="key-contention" value={contention} onValueChange={(value) => setContention(value === "ratio" ? "ratio" : "equal")}
                options={[{ value: "equal", label: "Equal split" }, { value: "ratio", label: "By pool size" }]} />
            </Field>
          </AdvancedSection>
        )}
        {error && <p role="alert" className="fs-field-error">{error}</p>}
        <FormActions><Button type="button" variant="outline" size="form" onClick={onClose}>Cancel</Button><Button type="submit" size="form" pending={pending}>{action}</Button></FormActions>
      </form>
    </Modal>
  )
}
