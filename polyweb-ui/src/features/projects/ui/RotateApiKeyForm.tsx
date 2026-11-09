import { useState } from "react"
import type { FormEvent } from "react"
import { Button } from "@/shared/ui/button"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Select } from "@/shared/ui/select"
import type { ProjectApiKey } from "@/domains/projects"
import { toApiKeyExpiry, type ExpiryChoice } from "../model/expiryChoice"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ExpirationField } from "./ExpirationField"

/** Overlap options: how long the old key stays valid after the rotation. */
const OVERLAP_OPTIONS = [
  { value: "0", label: "Revoke old key now" },
  { value: "3600", label: "1 hour" },
  { value: "86400", label: "24 hours" },
  { value: "604800", label: "7 days" },
]
const DEFAULT_OVERLAP_SECONDS = 86_400

/**
 * Rotate form of one key; the dialog mounts it fresh for every opened key.
 *
 * The overlap defaults to 24 hours and "Keep current" omits `expires_at`.
 * A past custom date shows under the date field; a failure of the rotation
 * shows at the top of the form, inside the dialog.
 */
export function RotateApiKeyForm({
  apiKey,
  controller,
}: {
  apiKey: ProjectApiKey
  controller: ProjectApiKeysController
}) {
  const [overlap, setOverlap] = useState(DEFAULT_OVERLAP_SECONDS)
  const [choice, setChoice] = useState<ExpiryChoice>("default")
  const [customDate, setCustomDate] = useState("")
  const [dateError, setDateError] = useState<string | null>(null)

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const expiry = toApiKeyExpiry(choice, customDate)
    if (!expiry.ok) {
      setDateError(expiry.message)
      return
    }
    setDateError(null)
    void controller.rotate(apiKey, { overlapSeconds: overlap, expiry: expiry.expiry })
  }

  return (
    <form className="space-y-4" onSubmit={submit} noValidate>
      {controller.message !== null && (
        <p role="alert" className="text-[13px] text-[var(--status-danger)]">
          {controller.message}
        </p>
      )}
      <Field id="rotate-overlap" label="Old key stays valid for">
        <Select
          id="rotate-overlap"
          value={String(overlap)}
          options={OVERLAP_OPTIONS}
          disabled={controller.pending}
          onValueChange={(value) => setOverlap(Number(value))}
        />
      </Field>
      <ExpirationField
        idPrefix="rotate"
        defaultLabel="Keep current"
        defaultHint="The new key keeps the old key's expiry date"
        choice={choice}
        customDate={customDate}
        disabled={controller.pending}
        error={dateError}
        onChoiceChange={setChoice}
        onCustomDateChange={setCustomDate}
      />
      <FormActions>
        <Button type="button" size="form" variant="outline" onClick={() => controller.openRotate(null)}>
          Cancel
        </Button>
        <Button type="submit" size="form" disabled={controller.pending}>
          Rotate key
        </Button>
      </FormActions>
    </form>
  )
}
