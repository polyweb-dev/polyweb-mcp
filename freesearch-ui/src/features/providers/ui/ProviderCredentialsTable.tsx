import { authModeLabel } from "@/domains/providers"
import type { AvailableCredential, ProjectCredential } from "@/domains/providers"
import { OperationTags } from "@/shared/ui/OperationTags"
import type { CredentialActions } from "../model/useCredentialActions"
import { CredentialRowActions } from "./CredentialRowActions"
import { CELL_CLASS, HEAD_CLASS } from "./formStyles"

function sentenceCase(value: string): string {
  return value.length === 0 ? value : value[0].toUpperCase() + value.slice(1)
}

const COLUMNS = ["Label", "Owner", "Auth", "Status", "Health", "Operations"]

interface ProviderCredentialsTableProps {
  name: string
  credentials: readonly AvailableCredential[]
  credentialsById: ReadonlyMap<string, ProjectCredential>
  /** The caller holds `credentials.manage_private` here. */
  canManagePrivate: boolean
  actions: CredentialActions
}

/** Credentials one project can bind for one provider type. */
export function ProviderCredentialsTable(props: ProviderCredentialsTableProps) {
  const { name, credentials, credentialsById, canManagePrivate, actions } = props
  return (
    <table aria-label={`${name} credentials`} className="w-full text-left text-[13px]">
      <thead>
        <tr className="border-b border-[var(--border-subtle)] text-[var(--muted)]">
          {COLUMNS.map((column) => (
            <th key={column} scope="col" className={HEAD_CLASS}>
              {column}
            </th>
          ))}
          <th scope="col" className={HEAD_CLASS}>
            <span className="sr-only">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {credentials.length === 0 && (
          <tr>
            <td colSpan={COLUMNS.length + 1} className="py-3 text-[var(--muted)]">
              No credentials are available for this provider.
            </td>
          </tr>
        )}
        {credentials.map((credential) => {
          const managed = credentialsById.get(credential.id)
          const canManage = canManagePrivate && managed?.canManage === true
          return (
            <tr key={credential.id} className="border-b border-[var(--border-subtle)] text-[var(--text)]">
              <td className={CELL_CLASS}>{credential.label}</td>
              <td className={CELL_CLASS}>{credential.owner === "project" ? "Project" : "System (granted)"}</td>
              <td className={CELL_CLASS}>{authModeLabel(credential.authMode)}</td>
              <td className={CELL_CLASS}>{sentenceCase(credential.status)}</td>
              <td className={CELL_CLASS}>{sentenceCase(credential.health ?? "unknown")}</td>
              <td className={CELL_CLASS}>
                <OperationTags operations={credential.grantedOperations} />
              </td>
              <td className="py-2 align-top">
                {canManage && (
                  <CredentialRowActions
                    credential={{ id: credential.id, label: credential.label, generation: managed.generation }}
                    authMode={credential.authMode}
                    actions={actions}
                  />
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
