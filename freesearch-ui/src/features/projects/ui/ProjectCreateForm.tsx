import { useState } from "react"
import type { FormEvent } from "react"
import { useNavigate } from "react-router"
import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"
import { TextField } from "@/shared/ui/TextField"
import {
  createProject,
  projectMutationMessage,
  useProjects,
} from "@/domains/projects"

const NOT_A_MEMBER_MESSAGE = "Project created. You are not a member of it."

interface CreateErrors {
  name: string | null
  email: string | null
  form: string | null
}

const NO_ERRORS: CreateErrors = { name: null, email: null, form: null }

/** Route a server refusal: an email-shaped message belongs under the email field. */
function serverErrors(message: string): CreateErrors {
  return /email/i.test(message) ? { ...NO_ERRORS, email: message } : { ...NO_ERRORS, form: message }
}

/**
 * Project creation panel of the projects page.
 *
 * Renders only when the page gates it behind project creation. After a
 * successful create the provider reloads the list once: a member lands on
 * the new overview, a creator without membership (a system administrator)
 * gets a neutral note instead, since there is no implicit membership.
 */
export function ProjectCreateForm({ defaultAdminEmail }: { defaultAdminEmail: string }) {
  const { reloadProjects } = useProjects()
  const navigate = useNavigate()
  const [name, setName] = useState("")
  const [adminEmail, setAdminEmail] = useState(defaultAdminEmail)
  const [pending, setPending] = useState(false)
  const [errors, setErrors] = useState<CreateErrors>(NO_ERRORS)
  const [note, setNote] = useState<string | null>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmedName = name.trim()
    const trimmedEmail = adminEmail.trim()
    const invalid: CreateErrors = {
      name: trimmedName ? null : "Enter a project name",
      email: trimmedEmail ? null : "Enter the first administrator's email address",
      form: null,
    }
    setNote(null)
    setErrors(invalid)
    if (invalid.name !== null || invalid.email !== null) return
    setPending(true)
    try {
      const created = await createProject({ name: trimmedName, initial_admin_email: trimmedEmail })
      const fresh = await reloadProjects()
      if (fresh !== null && fresh.some((project) => project.id === created.id)) {
        navigate(`/p/${created.id}`)
      } else {
        setName("")
        setNote(NOT_A_MEMBER_MESSAGE)
      }
    } catch (error) {
      setErrors(serverErrors(projectMutationMessage(error, "The project could not be created.", { emailLookup: true })))
    } finally {
      setPending(false)
    }
  }

  return (
    <section aria-labelledby="project-create-heading" className="fs-panel p-4">
      <h3 id="project-create-heading" className="fs-section-title">
        New project
      </h3>
      <form
        aria-label="Create project"
        className="mt-4 space-y-4"
        onSubmit={(event) => void submit(event)}
        noValidate
      >
        <TextField
          id="project-create-name"
          label="Project name"
          type="text"
          value={name}
          onChange={setName}
          disabled={pending}
          placeholder="e.g. Search team"
          error={errors.name}
        />
        <TextField
          id="project-create-admin-email"
          label="First administrator email"
          type="email"
          value={adminEmail}
          onChange={setAdminEmail}
          disabled={pending}
          autoComplete="email"
          error={errors.email}
        />
        {errors.form !== null && (
          <p role="alert" className="fs-field-error">
            {errors.form}
          </p>
        )}
        <FormActions
          start={note === null ? undefined : <span role="status">{note}</span>}
        >
          <Button type="submit" size="form" disabled={pending}>
            Create project
          </Button>
        </FormActions>
      </form>
    </section>
  )
}
