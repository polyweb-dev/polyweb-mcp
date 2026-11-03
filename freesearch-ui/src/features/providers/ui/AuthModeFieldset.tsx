import type { CredentialAuthMode } from "@/domains/providers"
import { LABEL_CLASS } from "./formStyles"

interface AuthModeFieldsetProps {
  name: string
  mode: CredentialAuthMode
  oauthAllowed: boolean
  disabled: boolean
  onChange: (mode: CredentialAuthMode) => void
}

/** "API key" / "OAuth" radio group; OAuth only where the provider allows it. */
export function AuthModeFieldset({ name, mode, oauthAllowed, disabled, onChange }: AuthModeFieldsetProps) {
  return (
    <fieldset className="space-y-1">
      <legend className={LABEL_CLASS}>Auth mode</legend>
      <label className="mr-4 inline-flex items-center gap-2 text-[13px]">
        <input
          type="radio"
          name={name}
          checked={mode === "api_key"}
          disabled={disabled}
          onChange={() => onChange("api_key")}
        />
        API key
      </label>
      {oauthAllowed && (
        <label className="inline-flex items-center gap-2 text-[13px]">
          <input
            type="radio"
            name={name}
            checked={mode === "oauth"}
            disabled={disabled}
            onChange={() => onChange("oauth")}
          />
          OAuth
        </label>
      )}
    </fieldset>
  )
}
