import { PROJECT_PERMISSIONS, hasPermission, useProjectScope } from "@/domains/projects"
import { credentialProviderTypes } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { PageHeader } from "@/shared/ui/PageHeader"
import { useProjectProvidersController } from "../model/useProjectProvidersController"
import { CredentialDialogs } from "./CredentialDialogs"
import { ProjectAllocations } from "./ProjectAllocations"
import { ProviderTypeSection } from "./ProviderTypeSection"
import { ALERT_CLASS, NOTE_CLASS } from "./formStyles"

const READ_ONLY_NOTE = "You can view providers. Ask a project administrator to change them."

/**
 * Providers of one project (`providers.read`, gated by the shell).
 *
 * Changing bindings needs `providers.configure`; adding, rotating and
 * deleting private keys needs `credentials.manage_private` plus the row's
 * `can_manage`. Allocations are read-only here.
 */
export function ProjectProvidersPage({ accountId }: { accountId: string }) {
  const { projectId, accessState } = useProjectScope()
  const access = accessState.status === "ready" ? accessState.data : null
  const canConfigure = hasPermission(access, PROJECT_PERMISSIONS.providersConfigure)
  const canManagePrivate = hasPermission(access, PROJECT_PERMISSIONS.credentialsManagePrivate)
  const controller = useProjectProvidersController({ accountId, projectId })
  const { view, credentialActions } = controller
  const message = controller.bindingStatus.message ?? credentialActions.status.message
  const notice = controller.bindingStatus.notice ?? credentialActions.status.notice

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <PageHeader
        title="Providers"
        description="Which providers this project runs, with which keys."
        actions={
          canManagePrivate ? (
            <Button size="form" onClick={() => credentialActions.openAdd(true)}>Add provider key</Button>
          ) : undefined
        }
      />

      {!canConfigure && <p role="note" className={NOTE_CLASS}>{READ_ONLY_NOTE}</p>}
      {message !== null && <p role="alert" className={ALERT_CLASS}>{message}</p>}
      {notice !== null && <p role="status" className="text-[13px] text-[var(--text)]">{notice}</p>}

      {view.status === "loading" && <p role="status" className={NOTE_CLASS}>Loading providers…</p>}
      {view.status === "error" && (
        <p role="alert" className={NOTE_CLASS}>The providers could not be loaded.</p>
      )}
      {view.status === "ready" && (
        <>
          {view.data.providers.map((provider) => (
            <ProviderTypeSection
              key={provider.providerType}
              provider={provider}
              controller={controller}
              canConfigure={canConfigure}
              canManagePrivate={canManagePrivate}
            />
          ))}
          <ProjectAllocations allocations={view.data.allocations} providers={view.data.providers} />
        </>
      )}

      {canManagePrivate && (
        <CredentialDialogs
          actions={credentialActions}
          addTitle="Add provider key"
          providerTypes={credentialProviderTypes()}
          onConnected={controller.reloadAll}
        />
      )}
    </section>
  )
}
