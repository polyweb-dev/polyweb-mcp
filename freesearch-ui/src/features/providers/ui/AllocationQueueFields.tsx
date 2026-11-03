import type { AllocationDraft } from "../model/allocationDraft"
import { FIELD_CLASS, LABEL_CLASS } from "./formStyles"

type QueueKey = "maxConcurrency" | "maxQueuedRequests" | "maxQueuedBytes" | "maxQueueWaitMs"

const QUEUE_FIELDS: { key: QueueKey; label: string }[] = [
  { key: "maxConcurrency", label: "Max concurrency" },
  { key: "maxQueuedRequests", label: "Max queued requests" },
  { key: "maxQueuedBytes", label: "Max queued bytes" },
  { key: "maxQueueWaitMs", label: "Max queue wait (ms)" },
]

interface AllocationQueueFieldsProps {
  draft: AllocationDraft
  disabled: boolean
  onChange: (patch: Partial<AllocationDraft>) => void
}

/** Optional queue bounds of one allocation; empty means no bound. */
export function AllocationQueueFields({ draft, disabled, onChange }: AllocationQueueFieldsProps) {
  return (
    <fieldset className="grid grid-cols-4 gap-3">
      <legend className={LABEL_CLASS}>Queue bounds (optional)</legend>
      {QUEUE_FIELDS.map(({ key, label }) => (
        <label key={key} className={LABEL_CLASS}>
          {label}
          <input
            type="number"
            min={0}
            value={draft[key]}
            disabled={disabled}
            onChange={(event) => onChange({ [key]: event.target.value })}
            className={FIELD_CLASS}
          />
        </label>
      ))}
    </fieldset>
  )
}
