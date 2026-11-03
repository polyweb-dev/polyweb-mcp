import { useState } from "react"
import type { FormEvent } from "react"
import type { AvailableCredential, NewBindingInput } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { FIELD_CLASS, LABEL_CLASS } from "./formStyles"

interface AddBindingFormProps {
  idPrefix: string
  credentials: readonly AvailableCredential[]
  pending: boolean
  onSubmit: (input: NewBindingInput) => Promise<boolean>
  onCancel: () => void
}

/** Create form of one binding: credential, route label and priority (default 100). */
export function AddBindingForm({ idPrefix, credentials, pending, onSubmit, onCancel }: AddBindingFormProps) {
  const [credentialId, setCredentialId] = useState(credentials[0]?.id ?? "")
  const [routeLabel, setRouteLabel] = useState("")
  const [priority, setPriority] = useState("100")
  const priorityValue = Number(priority)
  const valid =
    credentialId !== "" &&
    routeLabel.trim() !== "" &&
    Number.isInteger(priorityValue) &&
    priorityValue >= 0 &&
    priorityValue <= 1_000_000

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!valid) return
    const done = await onSubmit({ credentialId, routeLabel: routeLabel.trim(), priority: priorityValue })
    if (done) onCancel()
  }

  return (
    <form className="grid grid-cols-4 items-end gap-3" onSubmit={(event) => void submit(event)} noValidate>
      <div>
        <label htmlFor={`${idPrefix}-credential`} className={LABEL_CLASS}>
          Credential
        </label>
        <select
          id={`${idPrefix}-credential`}
          value={credentialId}
          disabled={pending}
          onChange={(event) => setCredentialId(event.target.value)}
          className={FIELD_CLASS}
        >
          {credentials.map((credential) => (
            <option key={credential.id} value={credential.id}>
              {credential.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor={`${idPrefix}-route`} className={LABEL_CLASS}>
          Route label
        </label>
        <input
          id={`${idPrefix}-route`}
          value={routeLabel}
          maxLength={100}
          disabled={pending}
          onChange={(event) => setRouteLabel(event.target.value)}
          className={FIELD_CLASS}
        />
      </div>
      <div>
        <label htmlFor={`${idPrefix}-priority`} className={LABEL_CLASS}>
          Priority
        </label>
        <input
          id={`${idPrefix}-priority`}
          type="number"
          min={0}
          max={1_000_000}
          value={priority}
          disabled={pending}
          onChange={(event) => setPriority(event.target.value)}
          className={FIELD_CLASS}
        />
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={pending || !valid}>
          Create binding
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
