import { useState } from "react"
import type { FormEvent } from "react"
import { Button } from "@/shared/ui/button"
import type { ProjectApiKey } from "@/domains/projects"
import { toApiKeyExpiry, type ExpiryChoice } from "../model/expiryChoice"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ExpirationRadioGroup } from "./ExpirationRadioGroup"

/** Overlap options: how long the old key stays valid after the rotation. */
const OVERLAP_OPTIONS: { seconds: number; label: string }[] = [
  { seconds: 0, label: "Revoke old key now" },
  { seconds: 3600, label: "1 hour" },
  { seconds: 86_400, label: "24 hours" },
  { seconds: 604_800, label: "7 days" },
]
const DEFAULT_OVERLAP_SECONDS = 86_400

/**
 * Rotate form of one key; the dialog mounts it fresh for every opened key.
 *
 * The overlap defaults to 24 hours and "Keep current lifetime" omits
 * `expires_at`. A failure of the rotation shows here, inside the dialog.
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

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const expiry = toApiKeyExpiry(choice, customDate)
    if (!expiry.ok) {
      controller.showMessage(expiry.message)
      return
    }
    void controller.rotate(apiKey, { overlapSeconds: overlap, expiry: expiry.expiry })
  }

  return (
    <form className="space-y-4" onSubmit={submit} noValidate>
      {controller.message !== null && (
        <p role="alert" className="text-[13px] text-[var(--status-danger)]">
          {controller.message}
        </p>
      )}
      <div>
        <label htmlFor="rotate-overlap" className="mb-1 block text-[12px] text-[var(--muted)]">
          Old key stays valid for
        </label>
        <select
          id="rotate-overlap"
          value={overlap}
          disabled={controller.pending}
          onChange={(event) => setOverlap(Number(event.target.value))}
          className="rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1.5 text-[13px] text-[var(--text)] outline-none focus-visible:border-[var(--signal)] disabled:opacity-60"
        >
          {OVERLAP_OPTIONS.map((option) => (
            <option key={option.seconds} value={option.seconds}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <ExpirationRadioGroup
        idPrefix="rotate"
        defaultLabel="Keep current lifetime"
        choice={choice}
        customDate={customDate}
        disabled={controller.pending}
        onChoiceChange={setChoice}
        onCustomDateChange={setCustomDate}
      />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={() => controller.openRotate(null)}>
          Cancel
        </Button>
        <Button type="submit" disabled={controller.pending}>
          Rotate key
        </Button>
      </div>
    </form>
  )
}
