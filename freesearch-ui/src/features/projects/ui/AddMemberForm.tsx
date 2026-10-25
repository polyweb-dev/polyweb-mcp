import type { FormEvent } from "react"
import { Button } from "@/shared/ui/button"
import { TextField } from "@/shared/ui/TextField"
import { PROJECT_ROLE_KEYS, PROJECT_ROLE_LABELS } from "@/domains/projects"
import type { ProjectRoleKey } from "@/domains/projects"
import type { ProjectMembersController } from "../model/useProjectMembersController"

/**
 * Add-member form of the members page.
 *
 * The form renders only under `members.manage` (the page gates it). Its draft
 * lives in the controller, which persists it under the project-scoped key.
 */
export function AddMemberForm({ controller }: { controller: ProjectMembersController }) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void controller.add()
  }

  return (
    <form
      aria-label="Add member"
      className="flex flex-wrap items-end gap-3 rounded border border-[var(--border-subtle)] p-4"
      onSubmit={submit}
      noValidate
    >
      <TextField
        id="member-add-email"
        label="Account email"
        type="email"
        value={controller.draft.email}
        onChange={(email) => controller.updateDraft({ ...controller.draft, email })}
        disabled={controller.pending}
        autoComplete="off"
      />
      <label className="flex flex-col gap-1 text-[13px] text-[var(--text)]">
        <span>Initial role</span>
        <select
          aria-label="Initial role"
          className="rounded border border-[var(--border-subtle)] bg-[var(--elevated)] px-2 py-1.5 text-[13px] text-[var(--text)]"
          value={controller.draft.role}
          disabled={controller.pending}
          onChange={(event) => {
            const role = event.target.value
            if ((PROJECT_ROLE_KEYS as readonly string[]).includes(role)) {
              controller.updateDraft({ ...controller.draft, role: role as ProjectRoleKey })
            }
          }}
        >
          {PROJECT_ROLE_KEYS.map((role) => (
            <option key={role} value={role}>
              {PROJECT_ROLE_LABELS[role]}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" disabled={controller.pending}>
        Add member
      </Button>
    </form>
  )
}
