import { useState } from "react"
import type { FormEvent } from "react"
import { providerTypeName, supportsOAuth } from "@/domains/providers"
import type { CredentialAuthMode, NewCredentialInput } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { SecretInput } from "@/shared/ui/SecretInput"
import { AuthModeFieldset } from "./AuthModeFieldset"
import { ALERT_CLASS, FIELD_CLASS, LABEL_CLASS } from "./formStyles"

interface CredentialFormProps {
  idPrefix: string
  providerTypes: readonly string[]
  pending: boolean
  /** Error text of the last failed save, shown inside the form. */
  error: string | null
  onSubmit: (input: NewCredentialInput) => Promise<boolean>
  onCancel: () => void
}

/**
 * Create form of one credential: provider, label, auth mode and, for an API
 * key, the write-only secret. The secret lives only in this form's state and
 * is cleared right after every save attempt, success or failure; cancel and
 * unmount drop it with the form.
 */
export function CredentialForm(props: CredentialFormProps) {
  const { idPrefix, providerTypes, pending, error, onSubmit, onCancel } = props
  const [providerType, setProviderType] = useState(providerTypes[0] ?? "")
  const [label, setLabel] = useState("")
  const [authMode, setAuthMode] = useState<CredentialAuthMode>("api_key")
  const [secret, setSecret] = useState("")
  const oauthAllowed = supportsOAuth(providerType)
  const mode: CredentialAuthMode = oauthAllowed ? authMode : "api_key"
  const ready = label.trim() !== "" && (mode === "oauth" || secret !== "")

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!ready) return
    const input = { providerType, label: label.trim(), authMode: mode, secret }
    setSecret("")
    await onSubmit(input)
  }

  return (
    <form className="space-y-4" onSubmit={(event) => void submit(event)} noValidate>
      {error !== null && (
        <p role="alert" className={ALERT_CLASS}>
          {error}
        </p>
      )}
      <div>
        <label htmlFor={`${idPrefix}-provider`} className={LABEL_CLASS}>
          Provider
        </label>
        <select
          id={`${idPrefix}-provider`}
          value={providerType}
          disabled={pending}
          onChange={(event) => setProviderType(event.target.value)}
          className={FIELD_CLASS}
        >
          {providerTypes.map((type) => (
            <option key={type} value={type}>
              {providerTypeName(type)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor={`${idPrefix}-label`} className={LABEL_CLASS}>
          Label
        </label>
        <input
          id={`${idPrefix}-label`}
          value={label}
          maxLength={100}
          disabled={pending}
          onChange={(event) => setLabel(event.target.value)}
          className={FIELD_CLASS}
        />
      </div>
      <AuthModeFieldset
        name={`${idPrefix}-auth`}
        mode={mode}
        oauthAllowed={oauthAllowed}
        disabled={pending}
        onChange={setAuthMode}
      />
      {mode === "api_key" && (
        <SecretInput
          id={`${idPrefix}-secret`}
          label="API key"
          value={secret}
          onChange={setSecret}
          disabled={pending}
        />
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending || !ready}>
          Save key
        </Button>
      </div>
    </form>
  )
}
