import type { FormEvent } from "react"
import { Button } from "@/shared/ui/button"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Select } from "@/shared/ui/select"
import { TextField } from "@/shared/ui/TextField"
import { isProjectRoleKey, memberPermissionSummary, PERMISSION_PRESETS } from "@/domains/projects"
import { isEmailFieldMessage } from "../model/useProjectMembersController"
import type { ProjectMembersController } from "../model/useProjectMembersController"

const EMAIL_ID = "member-add-email"
const ROLE_OPTIONS = [
  { value: "project_member", label: "Developer" },
  { value: "project_admin", label: "Project admin" },
]

/**
 * Add-member panel of the members page.
 *
 * The form renders only under `members.manage` (the page gates it). Its draft
 * lives in the controller, which persists it under the project-scoped key.
 * An email-shaped refusal lands under the email field with the focus on it;
 * any other server error stays as the page alert.
 */
export function AddMemberForm({ controller }: { controller: ProjectMembersController }) {
  const fieldError =
    controller.message !== null && isEmailFieldMessage(controller.message)
      ? controller.message
      : null

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    // The field stays disabled until the submit settles; the focus lands on
    // the next task, once React has flipped the disabled attribute back.
    void controller.add().finally(() => {
      window.setTimeout(() => document.getElementById(EMAIL_ID)?.focus(), 0)
    })
  }

  return (
    <section aria-labelledby="member-add-heading" className="fs-panel p-4">
      <h3 id="member-add-heading" className="fs-section-title">
        New member
      </h3>
      <form aria-label="Add member" className="mt-4 space-y-4" onSubmit={submit} noValidate>
        <TextField
          id={EMAIL_ID}
          label="Account email"
          type="email"
          placeholder="name@example.com"
          value={controller.draft.email}
          onChange={(email) => controller.updateDraft({ ...controller.draft, email })}
          disabled={controller.pending}
          autoComplete="off"
          error={fieldError}
        />
        <Field id="member-add-role" label="Role" hint={controller.draft.role === "project_member" ? `Starts with ${memberPermissionSummary(PERMISSION_PRESETS.Standard)}. Change them from the row menu` : undefined}>
          <Select
            id="member-add-role"
            value={controller.draft.role}
            options={ROLE_OPTIONS}
            disabled={controller.pending}
            onValueChange={(role) => {
              if (isProjectRoleKey(role)) controller.updateDraft({ ...controller.draft, role })
            }}
          />
        </Field>
        <FormActions>
          <Button type="submit" size="form" disabled={controller.pending}>
            Add member
          </Button>
        </FormActions>
      </form>
    </section>
  )
}
