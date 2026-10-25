import { useState } from "react"
import type { FormEvent } from "react"
import { useNavigate } from "react-router"
import { Button } from "@/shared/ui/button"
import { TextField } from "@/shared/ui/TextField"
import {
  createProject,
  projectMutationMessage,
  useProjects,
} from "@/domains/projects"

const NOT_A_MEMBER_MESSAGE = "Project created. You are not a member of it."

/**
 * Project creation form.
 *
 * Renders only when the page gates it behind `project.create`. After a
 * successful create the provider reloads the list once; the effect that
 * watches it then decides: a member lands on the new overview, a creator
 * without membership (a system administrator) gets a neutral note instead —
 * there is no implicit membership.
 */
export function ProjectCreateForm({ defaultAdminEmail }: { defaultAdminEmail: string }) {
  const { reloadProjects } = useProjects()
  const navigate = useNavigate()
  const [name, setName] = useState("")
  const [adminEmail, setAdminEmail] = useState(defaultAdminEmail)
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmedName = name.trim()
    const trimmedEmail = adminEmail.trim()
    if (!trimmedName || !trimmedEmail) {
      setMessage("Enter a project name and the first administrator's email address.")
      return
    }
    setPending(true)
    setMessage(null)
    try {
      const created = await createProject({
        name: trimmedName,
        initial_admin_email: trimmedEmail,
      })
      const fresh = await reloadProjects()
      if (fresh !== null && fresh.some((project) => project.id === created.id)) {
        navigate(`/p/${created.id}`)
      } else {
        setName("")
        setMessage(NOT_A_MEMBER_MESSAGE)
      }
    } catch (error) {
      setMessage(projectMutationMessage(error, "The project could not be created."))
    } finally {
      setPending(false)
    }
  }

  return (
    <form
      aria-label="Create project"
      className="space-y-4 rounded border border-[var(--border-subtle)] p-4"
      onSubmit={(event) => void submit(event)}
      noValidate
    >
      {message !== null && (
        <p role="status" className="text-[13px] text-[var(--muted)]">
          {message}
        </p>
      )}
      <TextField
        id="project-create-name"
        label="Project name"
        type="text"
        value={name}
        onChange={setName}
        disabled={pending}
      />
      <TextField
        id="project-create-admin-email"
        label="First administrator email"
        type="email"
        value={adminEmail}
        onChange={setAdminEmail}
        disabled={pending}
        autoComplete="email"
      />
      <Button type="submit" disabled={pending}>
        Create project
      </Button>
    </form>
  )
}
