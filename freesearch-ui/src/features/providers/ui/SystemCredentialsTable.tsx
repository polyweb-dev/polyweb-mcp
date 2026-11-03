import { authModeLabel, providerTypeName } from "@/domains/providers"
import type { SystemCredential } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import type { CredentialActions } from "../model/useCredentialActions"
import { CredentialRowActions } from "./CredentialRowActions"
import { CELL_CLASS, HEAD_CLASS } from "./formStyles"

const COLUMNS = ["Provider", "Label", "Auth", "Generation", "Status"]

interface SystemCredentialsTableProps {
  credentials: readonly SystemCredential[]
  actions: CredentialActions
  onGrants: (credential: SystemCredential) => void
}

/** System credential metadata; it never shows a secret. */
export function SystemCredentialsTable({ credentials, actions, onGrants }: SystemCredentialsTableProps) {
  return (
    <table aria-label="System credentials" className="w-full text-left text-[13px]">
      <thead>
        <tr className="border-b border-[var(--border-subtle)] text-[var(--muted)]">
          {COLUMNS.map((column) => (
            <th key={column} scope="col" className={HEAD_CLASS}>{column}</th>
          ))}
          <th scope="col" className={HEAD_CLASS}><span className="sr-only">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {credentials.length === 0 && (
          <tr><td colSpan={COLUMNS.length + 1} className="py-3 text-[var(--muted)]">No system credentials yet.</td></tr>
        )}
        {credentials.map((credential) => (
          <tr key={credential.id} className="border-b border-[var(--border-subtle)] text-[var(--text)]">
            <td className={CELL_CLASS}>{providerTypeName(credential.providerType)}</td>
            <td className={CELL_CLASS}>{credential.label}</td>
            <td className={CELL_CLASS}>{authModeLabel(credential.authMode)}</td>
            <td className={`${CELL_CLASS} tnum`}>{credential.generation}</td>
            <td className={CELL_CLASS}>{credential.status}</td>
            <td className="py-2 align-top">
              <div className="flex justify-end gap-1">
                <Button size="sm" variant="outline" aria-label={`Grants ${credential.label}`} onClick={() => onGrants(credential)}>
                  Grants
                </Button>
                <CredentialRowActions credential={credential} authMode={credential.authMode} actions={actions} />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
