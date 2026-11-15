import type { ReactNode } from "react"
import type { TraceActor } from "@/domains/activity"
import { UNKNOWN_USER_LABEL } from "@/shared/lib/identity"
import { IdentityLines } from "@/shared/ui/IdentityLines"

const API_KEY_LABEL = "API key"

/**
 * "Initiated by" cell shared by the Activity list, the trace detail rail, and
 * the project overview.
 *
 * - API-key actor: the key name is the primary line, with a muted
 *   `API key · <prefix>` line (prefix in monospace, as on the API keys page).
 *   A key that no longer exists has neither, and shows the plain `API key`.
 * - Human actor: the display name only (full name, else username, else
 *   `Unknown user`). An email is never shown here.
 * - Legacy rows with no actor information stay quiet (`—`).
 */
export function TraceActorCell({ actor }: { actor: TraceActor }): ReactNode {
  if (actor.kind === "project_api_key") {
    if (actor.apiKeyName === null) {
      return actor.apiKeyPrefix === null ? (
        API_KEY_LABEL
      ) : (
        <IdentityLines primary={API_KEY_LABEL} secondaryMono={actor.apiKeyPrefix} />
      )
    }
    return (
      <IdentityLines primary={actor.apiKeyName} secondary={`${API_KEY_LABEL} ·`} secondaryMono={actor.apiKeyPrefix} />
    )
  }
  if (actor.displayName !== null) return <IdentityLines primary={actor.displayName} />
  return actor.kind === "human" ? UNKNOWN_USER_LABEL : "—"
}
