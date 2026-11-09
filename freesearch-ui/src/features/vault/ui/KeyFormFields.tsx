import type { ReactNode } from "react"
import { SecretInput } from "@/shared/ui/SecretInput"
import { TextField } from "@/shared/ui/TextField"

export function KeyFormFields({ idPrefix, label, setLabel, secret, setSecret, submitted, showLabel = true, showSecret = true, children }: {
  idPrefix: string
  label: string
  setLabel: (value: string) => void
  secret: string
  setSecret: (value: string) => void
  submitted: boolean
  showLabel?: boolean
  showSecret?: boolean
  children?: ReactNode
}) {
  return <>
    {showLabel && <TextField id={`${idPrefix}-label`} label="Label" type="text" value={label} onChange={setLabel}
      error={submitted && !label.trim() ? "Enter a label" : null} />}
    {children}
    {showSecret && <SecretInput id={`${idPrefix}-secret`} label="API key" value={secret} onChange={setSecret}
      error={submitted && !secret.trim() ? "Enter the API key" : null} />}
  </>
}
