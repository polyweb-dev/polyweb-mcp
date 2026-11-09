import { useState } from "react"
import type { FormEvent } from "react"
import { Button } from "@/shared/ui/button"
import { Checkbox } from "@/shared/ui/Checkbox"
import { FormActions } from "@/shared/ui/FormActions"
import { TextField } from "@/shared/ui/TextField"
import { API_KEY_SCOPES, API_KEY_SCOPE_LABELS } from "@/domains/projects"
import type { ApiKeyScope } from "@/domains/projects"
import { toApiKeyExpiry, type ExpiryChoice } from "../model/expiryChoice"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ExpirationField } from "./ExpirationField"

export interface IssueApiKeyFormProps {
  controller: ProjectApiKeysController
  /** Execution scopes the caller holds in this project; others stay disabled. */
  permittedScopes: readonly ApiKeyScope[]
}

interface IssueErrors {
  label: string | null
  scopes: string | null
  expiry: string | null
}

const NO_ERRORS: IssueErrors = { label: null, scopes: null, expiry: null }

/**
 * Issue panel of the API keys page.
 *
 * Its state is local and never persisted: a key form keeps no draft. Every
 * permitted scope is checked until the user unchecks it; a scope the caller
 * lacks is disabled, because the server refuses to delegate it. The default
 * expiration omits `expires_at` (90 days), "No expiration" sends an explicit
 * `null`. Validation errors sit under their fields; a server refusal stays
 * the page alert.
 */
export function IssueApiKeyForm({ controller, permittedScopes }: IssueApiKeyFormProps) {
  const [label, setLabel] = useState("")
  const [unchecked, setUnchecked] = useState<readonly ApiKeyScope[]>([])
  const [choice, setChoice] = useState<ExpiryChoice>("default")
  const [customDate, setCustomDate] = useState("")
  const [errors, setErrors] = useState<IssueErrors>(NO_ERRORS)
  const selected = permittedScopes.filter((scope) => !unchecked.includes(scope))

  const toggle = (scope: ApiKeyScope, checked: boolean) => {
    setUnchecked((current) =>
      checked ? current.filter((item) => item !== scope) : [...current, scope]
    )
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmed = label.trim()
    const expiry = toApiKeyExpiry(choice, customDate)
    const found: IssueErrors = {
      label: trimmed ? null : "Enter a label for the key",
      scopes: selected.length > 0 ? null : "Choose at least one scope",
      expiry: expiry.ok ? null : expiry.message,
    }
    setErrors(found)
    if (!expiry.ok || found.label !== null || found.scopes !== null) return
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
    <section aria-labelledby="issue-api-key-heading" className="fs-panel p-4">
      <h3 id="issue-api-key-heading" className="fs-section-title">
        New API key
      </h3>
      <form className="mt-4 space-y-4" onSubmit={(event) => void submit(event)} noValidate>
        <TextField
          id="api-key-label"
          label="Label"
          type="text"
          value={label}
          onChange={setLabel}
          disabled={controller.pending}
          autoComplete="off"
          placeholder="ci-pipeline"
          error={errors.label}
        />
        <fieldset aria-describedby={errors.scopes === null ? undefined : "api-key-scopes-error"}>
          <legend className="fs-label">Scopes</legend>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            {API_KEY_SCOPES.map((scope) => (
              <Checkbox
                key={scope}
                id={`api-key-scope-${scope}`}
                label={API_KEY_SCOPE_LABELS[scope]}
                checked={selected.includes(scope)}
                disabled={controller.pending || !permittedScopes.includes(scope)}
                onChange={(checked) => toggle(scope, checked)}
              />
            ))}
          </div>
          {errors.scopes !== null && (
            <p id="api-key-scopes-error" role="alert" className="fs-field-error">
              {errors.scopes}
            </p>
          )}
        </fieldset>
        <ExpirationField
          idPrefix="issue"
          defaultLabel="90 days"
          defaultHint="The key stops working 90 days after it is issued"
          choice={choice}
          customDate={customDate}
          disabled={controller.pending}
          error={errors.expiry}
          onChoiceChange={setChoice}
          onCustomDateChange={setCustomDate}
        />
        <FormActions>
          <Button type="submit" size="form" disabled={controller.pending}>
            Issue key
          </Button>
        </FormActions>
      </form>
    </section>
  )
}
