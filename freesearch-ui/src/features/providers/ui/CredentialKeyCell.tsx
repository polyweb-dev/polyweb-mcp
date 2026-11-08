import type { AvailableCredential } from "@/domains/providers"
import { Tag } from "@/shared/ui/Tag"
import { isKeylessCredential, readableWord } from "../model/credentialDisplay"

interface CredentialKeyCellProps {
  providerType: string
  /** `null` when the route's key is no longer available to the project. */
  credential: AvailableCredential | null
}

/**
 * The key of one row: its label, tagged only for the exceptions (a project
 * key, OAuth, a status other than active), or a single "Keyless" tag for a
 * provider's keyless tier. System keys carry no tag. Never a raw key id.
 */
export function CredentialKeyCell({ providerType, credential }: CredentialKeyCellProps) {
  if (credential === null) return <span className="text-[var(--muted)]">Key unavailable</span>
  if (isKeylessCredential(providerType, credential)) return <Tag>Keyless</Tag>
  return (
    <span className="inline-flex min-w-0 flex-wrap items-center gap-2">
      <span className="min-w-0 [overflow-wrap:anywhere]">{credential.label}</span>
      {credential.owner === "project" && <Tag>Project key</Tag>}
      {credential.authMode === "oauth" && <Tag>OAuth</Tag>}
      {credential.status !== "active" && <Tag tone="warning">{readableWord(credential.status)}</Tag>}
    </span>
  )
}
