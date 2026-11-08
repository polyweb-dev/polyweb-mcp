import { useState } from "react"
import type { FormEvent } from "react"
import { credentialProviderTypes, providerIdentity, providerTypeName, supportsOAuth } from "@/domains/providers"
import { createVaultKey, rotateVaultKey, updateVaultKey } from "@/domains/vault"
import type { VaultKey } from "@/domains/vault"
import { ApiError } from "@/shared/api/http"
import { AdvancedSection } from "@/shared/ui/AdvancedSection"
import { Button } from "@/shared/ui/button"
import { Checkbox } from "@/shared/ui/Checkbox"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { ProviderSelect } from "@/shared/ui/ProviderSelect"
import { Select } from "@/shared/ui/select"
import { SecretInput } from "@/shared/ui/SecretInput"
import { TextField } from "@/shared/ui/TextField"

type Mode = "add" | "settings" | "rotate"

function invalidCapacity(capacity: string): boolean {
  return capacity !== "" && (!Number.isInteger(Number(capacity)) || Number(capacity) <= 0)
}

function needsSecret(mode: Mode, auth: string): boolean {
  return mode === "rotate" || (mode === "add" && auth === "api_key")
}

function requiredError(submitted: boolean, value: string, message: string): string | null {
  return submitted && !value.trim() ? message : null
}

function capacityToSave(form: HTMLFormElement, capacity: string, initial: string): string {
  return !form.elements.namedItem("key-limit") && invalidCapacity(capacity) ? initial : capacity
}

function invalidKeyValues({ mode, auth, label, capacity, secret }: {
  mode: Mode; auth: string; label: string; capacity: string; secret: string
}): boolean {
  return (mode !== "rotate" && (!label.trim() || invalidCapacity(capacity))) || (needsSecret(mode, auth) && !secret.trim())
}

function keySaveError(mode: Mode, err: unknown): string {
  if (!(err instanceof ApiError) || err.status !== 409) return "The key did not save. Try again."
  if (mode === "rotate") return "The key changed in another window. Reload and try again."
  if (mode === "settings") return "The pool limits are more than the key limit. Turn on overcommit or lower the limit."
  return "The key did not save. A key with this label exists."
}

function initialKeyValues(item?: VaultKey) {
  return {
    provider: item?.provider_type ?? credentialProviderTypes()[0] ?? "",
    label: item?.label ?? "",
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

const TITLES: Record<Mode, string> = { add: "Add key", rotate: "Rotate key", settings: "Key settings" }
const ACTIONS: Record<Mode, string> = { add: "Save key", rotate: "Rotate key", settings: "Save settings" }

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
  const labelError = requiredError(submitted, label, "Enter a label")
  const secretError = requiredError(submitted, secret, "Enter the API key")

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
    <Modal isOpen onClose={onClose} title={title} maxWidth="lg">
      <form noValidate onSubmit={(event) => void save(event)} className="space-y-4">
        {mode === "rotate" && <p>Enter the new API key. Each pool that uses this key switches to it at once</p>}
        {mode === "add" && (
          <Field id="vault-provider" label="Provider">
            <ProviderSelect id="vault-provider" value={providerIdentity(provider).id}
              options={credentialProviderTypes().map((type) => ({ value: providerIdentity(type).id, label: providerTypeName(type) }))}
              onValueChange={(value) => { setProvider(credentialProviderTypes().find((type) => providerIdentity(type).id === value) ?? value); setAuth("api_key") }} />
          </Field>
        )}
        {mode !== "rotate" && <TextField id="vault-label" label="Label" type="text" value={label} onChange={setLabel} error={labelError} />}
        {mode === "add" && supportsOAuth(provider) && (
          <Field id="vault-auth" label="Authentication">
            <Select id="vault-auth" value={auth} onValueChange={setAuth}
              options={[{ value: "api_key", label: "API key" }, { value: "oauth", label: "OAuth" }]} />
          </Field>
        )}
        {needsSecret(mode, auth) && <SecretInput id="vault-secret" label="API key" value={secret} onChange={setSecret} error={secretError} />}
        {mode !== "rotate" && (
          <AdvancedSection label="Advanced">
            <TextField id="key-limit" label="Key limit" type="number" min="1" value={capacity} onChange={setCapacity} error={submitted && invalidCapacity(capacity) ? "Enter a positive whole number" : null} hint="Enter the requests that the provider allows for this key, or leave empty if unknown" />
            <Field id="key-window" label="Rate unit">
              <Select id="key-window" value={String(windowSeconds)} onValueChange={(value) => setWindowSeconds(Number(value))}
                options={[{ value: "1", label: "Per second" }, { value: "60", label: "Per minute" }, { value: "3600", label: "Per hour" }]} />
            </Field>
            <Checkbox checked={overcommit} onChange={setOvercommit} label="Allow overcommit" description="Pool limits can exceed the key limit. A busy pool can use idle capacity from other pools" />
            <Field id="key-contention" label="When pools compete">
              <Select id="key-contention" value={contention} onValueChange={(value) => setContention(value === "ratio" ? "ratio" : "equal")}
                options={[{ value: "equal", label: "Equal split" }, { value: "ratio", label: "By pool size" }]} />
            </Field>
          </AdvancedSection>
        )}
        {error && <p role="alert" className="fs-field-error">{error}</p>}
        <FormActions><Button type="button" variant="outline" size="form" onClick={onClose}>Cancel</Button><Button type="submit" size="form" disabled={pending}>{action}</Button></FormActions>
      </form>
    </Modal>
  )
}
