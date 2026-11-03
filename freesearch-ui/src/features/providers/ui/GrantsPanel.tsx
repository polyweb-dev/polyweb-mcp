import { useState } from "react"
import type { Project } from "@/domains/projects"
import { supportedOperationsOf } from "@/domains/providers"
import type { CredentialGrant, SystemCredential } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { useCredentialGrants } from "../model/useCredentialGrants"
import { GrantForm } from "./GrantForm"
import { ALERT_CLASS, CELL_CLASS, HEAD_CLASS, NOTE_CLASS } from "./formStyles"

interface GrantsPanelProps {
  credential: SystemCredential
  projects: readonly Project[]
}

function projectName(projectId: string, projects: readonly Project[]): string {
  return projects.find((project) => project.id === projectId)?.name ?? projectId
}

/** Project grants of one system credential: list, add, edit and remove. */
export function GrantsPanel({ credential, projects }: GrantsPanelProps) {
  const controller = useCredentialGrants(credential.id)
  const [editing, setEditing] = useState<CredentialGrant | null>(null)
  const supported = supportedOperationsOf(credential.providerType)
  const { grants } = controller

  const save = async (projectId: string, operations: Parameters<typeof controller.save>[1]) => {
    const done = await controller.save(projectId, operations)
    if (done) setEditing(null)
    return done
  }

  return (
    <div className="space-y-4">
      {controller.message !== null && <p role="alert" className={ALERT_CLASS}>{controller.message}</p>}
      {grants.status === "loading" && <p role="status" className={NOTE_CLASS}>Loading grants…</p>}
      {grants.status === "error" && <p role="alert" className={NOTE_CLASS}>The grants could not be loaded.</p>}
      {grants.status === "ready" && (
        <table aria-label="Project grants" className="w-full text-left text-[13px]">
          <thead>
            <tr className="border-b border-[var(--border-subtle)] text-[var(--muted)]">
              <th scope="col" className={HEAD_CLASS}>Project</th>
              <th scope="col" className={HEAD_CLASS}>Operations</th>
              <th scope="col" className={HEAD_CLASS}><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {grants.data.length === 0 && (
              <tr><td colSpan={3} className="py-3 text-[var(--muted)]">No project can use this credential yet.</td></tr>
            )}
            {grants.data.map((grant) => {
              const name = projectName(grant.projectId, projects)
              return (
                <tr key={grant.projectId} className="border-b border-[var(--border-subtle)]">
                  <td className={CELL_CLASS}>{name}</td>
                  <td className={CELL_CLASS}>{grant.permittedOperations.join(", ") || "none"}</td>
                  <td className="flex justify-end gap-1 py-2">
                    <Button size="sm" variant="outline" aria-label={`Edit grant ${name}`} disabled={controller.pending} onClick={() => setEditing(grant)}>Edit</Button>
                    <Button size="sm" variant="destructive" aria-label={`Remove grant ${name}`} disabled={controller.pending} onClick={() => void controller.remove(grant.projectId)}>Remove</Button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      <GrantForm
        key={editing?.projectId ?? "new"}
        projects={projects}
        supported={supported}
        initial={editing === null ? null : { projectId: editing.projectId, operations: editing.permittedOperations }}
        pending={controller.pending}
        onSubmit={save}
      />
    </div>
  )
}
