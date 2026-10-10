import { useState } from "react"
import type { FormEvent } from "react"
import { Link } from "react-router"
import { Button } from "@/shared/ui/button"
import { authErrorText, registerAccount } from "@/domains/auth"
import type { UserAccount, UserRole } from "@/domains/auth"
import { LOGIN_PATH } from "@/app/routes"
import {
  AUTH_FOOTER_CLASSES,
  AUTH_FOOTER_TEXT_CLASSES,
  AUTH_LINK_CLASSES,
  AUTH_SUBMIT_CLASSES,
  AuthPanel,
} from "./AuthPanel"
import { RegisterSuccess } from "./RegisterSuccess"
import { RoleField } from "./RoleField"
import { TextField } from "@/shared/ui/TextField"

/** The accepted password rule of the backend user manager. */
export const MIN_PASSWORD_LENGTH = 12
export const MAX_PASSWORD_LENGTH = 128

const PASSWORD_HINT = `Use ${MIN_PASSWORD_LENGTH} to ${MAX_PASSWORD_LENGTH} characters.`
const REGISTER_FAILURE = "Registration failed. Check the email address and the password rule."

function validate(email: string, password: string, confirmation: string): string | null {
  if (!email.trim()) return "Enter your email address."
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Use at least ${MIN_PASSWORD_LENGTH} characters for the password.`
  }
  if (password.length > MAX_PASSWORD_LENGTH) {
    return `Use no more than ${MAX_PASSWORD_LENGTH} characters for the password.`
  }
  if (password !== confirmation) return "The two passwords do not match."
  return null
}

/**
 * Registration screen.
 *
 * Public registration creates an account in the selected role and returns no
 * credential. The role select starts on Agent, and the server stays
 * authoritative for the role, the email, and the password rule. The screen
 * confirms the creation with the stored role and returns to login, and it never
 * signs the new account in automatically.
 */
export function RegisterPage() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [role, setRole] = useState<UserRole>("agent")
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [created, setCreated] = useState<UserAccount | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (pending) return
    const problem = validate(email, password, confirmation)
    if (problem !== null) {
      setError(problem)
      return
    }
    setPending(true)
    setError(null)
    try {
      const account = await registerAccount({ email, password, role })
      setPassword("")
      setConfirmation("")
      setCreated(account)
    } catch (failure) {
      setError(authErrorText(failure, REGISTER_FAILURE))
    } finally {
      setPending(false)
    }
  }

  if (created !== null) return <RegisterSuccess role={created.role} />

  return (
    <AuthPanel title="Create an account" subtitle="Choose a role for the new account.">
      <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)} noValidate>
        <TextField
          id="register-email"
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          disabled={pending}
          autoComplete="email"
        />
        <TextField
          id="register-password"
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          disabled={pending}
          autoComplete="new-password"
          hint={PASSWORD_HINT}
        />
        <TextField
          id="register-confirmation"
          label="Confirm password"
          type="password"
          value={confirmation}
          onChange={setConfirmation}
          disabled={pending}
          autoComplete="new-password"
        />
        <RoleField role={role} onChange={setRole} disabled={pending} />
        {error !== null && (
          <p
            role="alert"
            className="rounded border border-[var(--status-danger)]/40 px-2.5 py-2 text-[13px]"
            style={{ color: "var(--status-danger)" }}
          >
            {error}
          </p>
        )}
        <Button type="submit" disabled={pending} className={AUTH_SUBMIT_CLASSES}>
          {pending ? "Creating account" : "Create account"}
        </Button>
      </form>
      <div className={AUTH_FOOTER_CLASSES}>
        <p className={AUTH_FOOTER_TEXT_CLASSES}>
          Already registered?{" "}
          <Link to={LOGIN_PATH} className={AUTH_LINK_CLASSES}>
            Sign in
          </Link>
        </p>
      </div>
    </AuthPanel>
  )
}
