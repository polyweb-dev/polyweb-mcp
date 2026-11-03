import { useCallback, useState } from "react"
import { useProjects } from "@/domains/projects"
import { credentialProviderTypes, listSystemCredentials } from "@/domains/providers"
import type { SystemCredential } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { Button } from "@/shared/ui/button"
import { Modal } from "@/shared/ui/Modal"
import { SYSTEM_CREDENTIAL_ROUTES } from "../model/credentialRoutes"
import { useCredentialActions } from "../model/useCredentialActions"
import { CredentialDialogs } from "./CredentialDialogs"
import { GrantsPanel } from "./GrantsPanel"
import { SystemCredentialsTable } from "./SystemCredentialsTable"
import { ALERT_CLASS, NOTE_CLASS } from "./formStyles"

/**
 * System credentials (`system.credentials.manage`, gated by the shell):
 * create, rotate, delete, OAuth connect and per-project grants.
 */
export function SystemCredentialsPage() {
  const { accountId, projects } = useProjects()
  const credentials = useScopedResource({
    scopeKey: `${accountId}:system-credentials`,
    load: (signal) => listSystemCredentials(signal),
  })
  const reloadCredentials = credentials.reload
  const reload = useCallback(() => void reloadCredentials(), [reloadCredentials])
  const actions = useCredentialActions(SYSTEM_CREDENTIAL_ROUTES, reload)
  const [grantsFor, setGrantsFor] = useState<SystemCredential | null>(null)
  const { message, notice } = actions.status

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <header className="flex items-end justify-between gap-4 border-b border-[var(--border-subtle)] pb-2">
        <div>
          <h1 className="text-[var(--text-strong)]">System credentials</h1>
          <p className="mt-0.5 text-[13px] text-[var(--muted)]">
            Provider keys owned by the installation, and which projects may use them.
          </p>
        </div>
        <Button onClick={() => actions.openAdd(true)}>Add system credential</Button>
      </header>
      {message !== null && <p role="alert" className={ALERT_CLASS}>{message}</p>}
      {notice !== null && <p role="status" className="text-[13px] text-[var(--text)]">{notice}</p>}
      {credentials.status === "loading" && <p role="status" className={NOTE_CLASS}>Loading credentials…</p>}
      {credentials.status === "error" && (
        <p role="alert" className={NOTE_CLASS}>The system credentials could not be loaded.</p>
      )}
      {credentials.status === "ready" && (
        <SystemCredentialsTable credentials={credentials.data} actions={actions} onGrants={setGrantsFor} />
      )}
      <CredentialDialogs
        actions={actions}
        addTitle="Add system credential"
        providerTypes={credentialProviderTypes()}
        onConnected={reload}
      />
      <Modal
        isOpen={grantsFor !== null}
        onClose={() => setGrantsFor(null)}
        title="Project grants"
        subtitle={grantsFor?.label}
        maxWidth="2xl"
      >
        {grantsFor !== null && <GrantsPanel key={grantsFor.id} credential={grantsFor} projects={projects} />}
      </Modal>
    </section>
  )
}
