import { useState } from "react"
import type { FormEvent } from "react"
import { Button } from "@/shared/ui/button"
import { TextField } from "@/shared/ui/TextField"
import { API_KEY_SCOPES, API_KEY_SCOPE_LABELS } from "@/domains/projects"
import type { ApiKeyScope } from "@/domains/projects"
import { toApiKeyExpiry, type ExpiryChoice } from "../model/expiryChoice"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ExpirationRadioGroup } from "./ExpirationRadioGroup"

export interface IssueApiKeyFormProps {
  controller: ProjectApiKeysController
  /** Execution scopes the caller holds in this project; others stay disabled. */
  permittedScopes: readonly ApiKeyScope[]
}

/**
 * Issue form of the API keys page.
 *
 * Its state is local and never persisted: a key form keeps no draft. Every
 * permitted scope is checked until the user unchecks it; a scope the caller
 * lacks is disabled, because the server refuses to delegate it. The default expiration omits
 * `expires_at` (90 days), "No expiration" sends an explicit `null`.
 */
export function IssueApiKeyForm({ controller, permittedScopes }: IssueApiKeyFormProps) {
  const [label, setLabel] = useState("")
  const [unchecked, setUnchecked] = useState<readonly ApiKeyScope[]>([])
  const [choice, setChoice] = useState<ExpiryChoice>("default")
  const [customDate, setCustomDate] = useState("")
  const selected = permittedScopes.filter((scope) => !unchecked.includes(scope))

  const toggle = (scope: ApiKeyScope, checked: boolean) => {
    setUnchecked((current) =>
      checked ? current.filter((item) => item !== scope) : [...current, scope]
    )
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmed = label.trim()
    if (!trimmed) return controller.showMessage("Enter a label for the key.")
    if (selected.length === 0) return controller.showMessage("Choose at least one scope.")
    const expiry = toApiKeyExpiry(choice, customDate)
    if (!expiry.ok) return controller.showMessage(expiry.message)
    const ordered = API_KEY_SCOPES.filter((scope) => selected.includes(scope))
    const issued = await controller.issue({ label: trimmed, scopes: ordered, expiry: expiry.expiry })
    if (issued) {
      setLabel("")
      setUnchecked([])
      setChoice("default")
      setCustomDate("")
    }
  }

  return (
    <section
      aria-labelledby="issue-api-key-heading"
      className="max-w-[480px] space-y-4 rounded border border-[var(--border-subtle)] p-4"
    >
      <h2 id="issue-api-key-heading" className="text-[13px] font-medium text-[var(--text-strong)]">
        Issue an API key
      </h2>
      <form className="space-y-4" onSubmit={(event) => void submit(event)} noValidate>
        <TextField
          id="api-key-label"
          label="Label"
          type="text"
          value={label}
          onChange={setLabel}
          disabled={controller.pending}
          autoComplete="off"
        />
        <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <legend className="mb-1 w-full text-[12px] text-[var(--muted)]">Scopes</legend>
          {API_KEY_SCOPES.map((scope) => (
            <label key={scope} className="flex items-center gap-2 text-[13px] text-[var(--text)]">
              <input
                type="checkbox"
                checked={selected.includes(scope)}
                disabled={controller.pending || !permittedScopes.includes(scope)}
                onChange={(event) => toggle(scope, event.target.checked)}
                className="accent-[var(--signal)]"
              />
              <span>{API_KEY_SCOPE_LABELS[scope]}</span>
            </label>
          ))}
        </fieldset>
        <ExpirationRadioGroup
          idPrefix="issue"
          defaultLabel="90 days (default)"
          choice={choice}
          customDate={customDate}
          disabled={controller.pending}
          onChoiceChange={setChoice}
          onCustomDateChange={setCustomDate}
        />
        <Button type="submit" size="form" disabled={controller.pending}>
          Issue key
        </Button>
      </form>
    </section>
  )
}
