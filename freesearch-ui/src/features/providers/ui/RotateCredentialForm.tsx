import { useState } from "react"
import type { FormEvent } from "react"
import { Button } from "@/shared/ui/button"
import { SecretInput } from "@/shared/ui/SecretInput"
import { ALERT_CLASS } from "./formStyles"

interface RotateCredentialFormProps {
  pending: boolean
  error: string | null
  onSubmit: (secret: string) => Promise<boolean>
  onCancel: () => void
}

/**
 * Rotate form: one write-only "New API key" field. The value is cleared
 * right after every attempt, and dies with the form on cancel and unmount.
 */
export function RotateCredentialForm({ pending, error, onSubmit, onCancel }: RotateCredentialFormProps) {
  const [secret, setSecret] = useState("")

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (secret === "") return
    const value = secret
    setSecret("")
    await onSubmit(value)
  }

  return (
    <form className="space-y-4" onSubmit={(event) => void submit(event)} noValidate>
      {error !== null && (
        <p role="alert" className={ALERT_CLASS}>
          {error}
        </p>
      )}
      <SecretInput
        id="rotate-credential-secret"
        label="New API key"
        value={secret}
        onChange={setSecret}
        disabled={pending}
      />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending || secret === ""}>
          Rotate key
        </Button>
      </div>
    </form>
  )
}
