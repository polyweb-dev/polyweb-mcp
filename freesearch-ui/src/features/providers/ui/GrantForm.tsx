import { useState } from "react"
import type { FormEvent } from "react"
import type { Project } from "@/domains/projects"
import type { ProviderOperation } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { FIELD_CLASS, LABEL_CLASS } from "./formStyles"

const OPERATION_LABELS: Record<ProviderOperation, string> = { search: "Search", fetch: "Fetch" }

interface GrantFormProps {
  projects: readonly Project[]
  /** Operations the credential's provider supports; only these are offered. */
  supported: readonly ProviderOperation[]
  initial: { projectId: string; operations: readonly ProviderOperation[] } | null
  pending: boolean
  onSubmit: (projectId: string, operations: ProviderOperation[]) => Promise<boolean>
}

/** Add or edit one project grant: project and permitted operations. */
export function GrantForm({ projects, supported, initial, pending, onSubmit }: GrantFormProps) {
  const [projectId, setProjectId] = useState(initial?.projectId ?? projects[0]?.id ?? "")
  const [operations, setOperations] = useState<ProviderOperation[]>(
    initial === null ? [...supported] : supported.filter((op) => initial.operations.includes(op))
  )

  const toggle = (operation: ProviderOperation, on: boolean) =>
    setOperations((previous) =>
      supported.filter((op) => (op === operation ? on : previous.includes(op)))
    )

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (projectId === "" || operations.length === 0) return
    await onSubmit(projectId, operations)
  }

  return (
    <form className="flex flex-wrap items-end gap-4" onSubmit={(event) => void submit(event)} noValidate>
      <div className="min-w-[200px]">
        <label htmlFor="grant-project" className={LABEL_CLASS}>
          Project
        </label>
        <select
          id="grant-project"
          value={projectId}
          disabled={pending || initial !== null}
          onChange={(event) => setProjectId(event.target.value)}
          className={FIELD_CLASS}
        >
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </div>
      {supported.map((operation) => (
        <label key={operation} className="inline-flex items-center gap-2 text-[13px]">
          <input
            type="checkbox"
            checked={operations.includes(operation)}
            disabled={pending}
            onChange={(event) => toggle(operation, event.target.checked)}
          />
          {OPERATION_LABELS[operation]}
        </label>
      ))}
      <Button type="submit" disabled={pending || projectId === "" || operations.length === 0}>
        Save grant
      </Button>
    </form>
  )
}
