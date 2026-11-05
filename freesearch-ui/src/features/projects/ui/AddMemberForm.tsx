import { useRef } from "react"
import type { FormEvent } from "react"
import { Button } from "@/shared/ui/button"
import { PROJECT_ROLE_KEYS, PROJECT_ROLE_LABELS } from "@/domains/projects"
import type { ProjectRoleKey } from "@/domains/projects"
import { isEmailFieldMessage } from "../model/useProjectMembersController"
import type { ProjectMembersController } from "../model/useProjectMembersController"

/**
 * Add-member form of the members page.
 *
 * The form renders only under `members.manage` (the page gates it). Its draft
 * lives in the controller, which persists it under the project-scoped key.
 * An email-shaped refusal lands under the email field with the focus on it;
 * any other server error stays as the page alert above the table.
 */
export function AddMemberForm({ controller }: { controller: ProjectMembersController }) {
  const emailRef = useRef<HTMLInputElement>(null)

  // A field-level refusal belongs under the email field; any other message
  // stays as the page alert above the table.
  const fieldError =
    controller.message !== null && isEmailFieldMessage(controller.message)
      ? controller.message
      : null

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    // The field stays disabled until the submit settles; the focus lands on
    // the next task, once React has flipped the disabled attribute back.
    void controller.add().finally(() => {
      window.setTimeout(() => emailRef.current?.focus(), 0)
    })
  }

  return (
    <form
      aria-label="Add member"
      className="flex flex-wrap items-end gap-3 rounded border border-[var(--border-subtle)] p-4"
      onSubmit={submit}
      noValidate
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="member-add-email" className="text-[12px] text-[var(--muted)]">
          Account email
        </label>
        <input
          id="member-add-email"
          type="email"
          value={controller.draft.email}
          onChange={(event) =>
            controller.updateDraft({ ...controller.draft, email: event.target.value })
          }
          disabled={controller.pending}
          autoComplete="off"
          ref={emailRef}
          aria-invalid={fieldError !== null}
          aria-describedby={fieldError !== null ? "member-add-email-error" : undefined}
          className="w-full rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1.5 text-[13px] text-[var(--text)] outline-none focus-visible:border-[var(--signal)] disabled:opacity-60 aria-[invalid=true]:border-[var(--status-danger)]"
        />
        {fieldError !== null && (
          <p id="member-add-email-error" role="alert" className="text-[12px] text-[var(--status-danger)]">
            {fieldError}
          </p>
        )}
      </div>
      <label className="flex flex-col gap-1 text-[13px] text-[var(--text)]">
        <span>Initial role</span>
        <select
          aria-label="Initial role"
          className="h-9 rounded border border-[var(--border-subtle)] bg-[var(--elevated)] px-2 text-[13px] text-[var(--text)]"
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
      <Button type="submit" size="form" disabled={controller.pending}>
        Add member
      </Button>
    </form>
  )
}
