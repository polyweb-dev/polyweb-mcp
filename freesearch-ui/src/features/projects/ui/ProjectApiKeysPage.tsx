import {
  API_KEY_SCOPES,
  PROJECT_PERMISSIONS,
  hasPermission,
  useProjectScope,
} from "@/domains/projects"
import { PageHeader } from "@/shared/ui/PageHeader"
import { useProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ApiKeyRevealDialog } from "./ApiKeyRevealDialog"
import { ApiKeysTable } from "./ApiKeysTable"
import { IssueApiKeyForm } from "./IssueApiKeyForm"
import { RotateApiKeyDialog } from "./RotateApiKeyDialog"

const ARCHIVED_NOTE = "This project is archived. Its keys can be revoked but not issued or rotated."

/**
 * API key management of one project (`tokens.manage`, gated by the shell).
 *
 * The issue form offers only the execution scopes the caller holds here. An
 * archived project hides issue and rotate. The raw key of an issue or a
 * rotation shows once in the reveal dialog and lives only in the page's
 * controller state, so it disappears on close, on unmount and on a project
 * switch.
 */
export function ProjectApiKeysPage({ accountId }: { accountId: string }) {
  const { projectId, project, accessState, refreshAccess } = useProjectScope()
  const access = accessState.status === "ready" ? accessState.data : null
  const controller = useProjectApiKeysController({
    accountId,
    projectId,
    refreshAccess,
    canReadMembers: hasPermission(access, PROJECT_PERMISSIONS.membersRead),
  })
  const archived = project?.status === "archived"
  const permittedScopes = API_KEY_SCOPES.filter((scope) => hasPermission(access, scope))
  const showPageMessage = controller.message !== null && controller.rotatingKey === null

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <PageHeader
        title="API keys"
        description={`Keys let programs call search and fetch in ${project?.name ?? "this project"}.`}
      />

      {showPageMessage && (
        <p role="alert" className="text-[13px] text-[var(--status-danger)]">
          {controller.message}
        </p>
      )}

      {archived ? (
        <p role="note" className="text-[13px] text-[var(--muted)]">
          {ARCHIVED_NOTE}
        </p>
      ) : (
        <IssueApiKeyForm controller={controller} permittedScopes={permittedScopes} />
      )}

      {controller.keys.status === "loading" && (
        <p role="status" className="text-[13px] text-[var(--muted)]">
          Loading API keys…
        </p>
      )}
      {controller.keys.status === "error" && (
        <p role="alert" className="text-[13px] text-[var(--muted)]">
          The API key list could not be loaded.
        </p>
      )}
      {controller.keys.status === "ready" && (
        <ApiKeysTable keys={controller.keys.data} controller={controller} archived={archived} />
      )}

      <RotateApiKeyDialog controller={controller} />
      <ApiKeyRevealDialog rawKey={controller.revealedKey} onDone={controller.dismissReveal} />
    </section>
  )
}
