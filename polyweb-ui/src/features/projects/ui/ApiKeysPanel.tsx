import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ApiKeysTable } from "./ApiKeysTable"

/** The key list of the API keys page in its load state: loading, failed or the table. */
export function ApiKeysPanel({ controller, archived }: { controller: ProjectApiKeysController; archived: boolean }) {
  const { keys } = controller
  if (keys.status === "loading") {
    return (
      <p role="status" className="text-[13px] text-[var(--muted)]">
        Loading API keys…
      </p>
    )
  }
  if (keys.status === "error") {
    return (
      <p role="alert" className="text-[13px] text-[var(--muted)]">
        The API key list could not be loaded.
      </p>
    )
  }
  return <ApiKeysTable keys={keys.data} controller={controller} archived={archived} />
}
