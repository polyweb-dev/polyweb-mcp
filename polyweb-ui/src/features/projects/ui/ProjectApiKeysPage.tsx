import {
  API_KEY_SCOPES,
  PROJECT_PERMISSIONS,
  hasPermission,
  useProjectScope,
} from "@/domains/projects"
import { PageHeader } from "@/shared/ui/PageHeader"
import { useProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ApiKeyRevealDialog } from "./ApiKeyRevealDialog"
import { ApiKeysPanel } from "./ApiKeysPanel"
import { IssueApiKeyForm } from "./IssueApiKeyForm"
import { RotateApiKeyDialog } from "./RotateApiKeyDialog"

const ARCHIVED_NOTE = "This project is archived. Its keys can be revoked but not issued or rotated."
const TWO_COLUMNS = "grid items-start gap-6 min-[1400px]:grid-cols-[minmax(0,1fr)_360px]"

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
  const pageMessage = controller.rotatingKey === null ? controller.message : null

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <PageHeader title="API keys" description="Keys for scripts and services that call search and fetch" />

      {pageMessage !== null && (
        <p role="alert" className="text-[13px] text-[var(--status-danger)]">
          {pageMessage}
        </p>
      )}

      {archived && (
        <p role="note" className="text-[13px] text-[var(--muted)]">
          {ARCHIVED_NOTE}
        </p>
      )}

      <div className={archived ? undefined : TWO_COLUMNS}>
        <div className="min-w-0">
          <ApiKeysPanel controller={controller} archived={archived} />
        </div>
        {!archived && <IssueApiKeyForm controller={controller} permittedScopes={permittedScopes} />}
      </div>

      <RotateApiKeyDialog controller={controller} />
      <ApiKeyRevealDialog rawKey={controller.revealedKey} onDone={controller.dismissReveal} />
    </section>
  )
}
