import { useState } from "react"
import type { FormEvent } from "react"
import { Link } from "react-router"
import { Button } from "@/shared/ui/button"
import { PASSWORD_HINT, authErrorText, passwordLengthProblem, registerAccount } from "@/domains/auth"
import type { UserAccount } from "@/domains/auth"
import { LOGIN_PATH } from "@/app/routes"
import {
  AUTH_FOOTER_CLASSES,
  AUTH_FOOTER_TEXT_CLASSES,
  AUTH_LINK_CLASSES,
  AUTH_SUBMIT_CLASSES,
  AuthPanel,
} from "./AuthPanel"
import { RegisterSuccess } from "./RegisterSuccess"
import { TextField } from "@/shared/ui/TextField"

const REGISTER_FAILURE = "Registration failed. Check the email address and the password rule."

function validate(email: string, password: string, confirmation: string): string | null {
  if (!email.trim()) return "Enter your email address."
  const lengthProblem = passwordLengthProblem(password)
  if (lengthProblem !== null) return lengthProblem
  if (password !== confirmation) return "The two passwords do not match."
  return null
}

/**
 * Registration screen.
 *
 * Public registration creates an ordinary account from the email and the
 * password only and returns no credential. There is no role or account-type
 * choice: authority comes from explicit system and project assignments. The
 * server stays authoritative for the email and the password rule. The screen
 * confirms the creation and returns to login, and it never signs the new
 * account in automatically.
 */
export function RegisterPage() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
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
      const account = await registerAccount({ email, password })
      setPassword("")
      setConfirmation("")
      setCreated(account)
    } catch (failure) {
      setError(authErrorText(failure, REGISTER_FAILURE))
    } finally {
      setPending(false)
    }
  }

  if (created !== null) return <RegisterSuccess />

  return (
    <AuthPanel title="Create an account" subtitle="Register with your email address.">
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
        {error !== null && (
          <p
            role="alert"
            className="rounded border border-[var(--status-danger)]/40 px-2.5 py-2 text-[13px]"
            style={{ color: "var(--status-danger)" }}
          >
            {error}
          </p>
        )}
        <Button type="submit" pending={pending} pendingLabel="Creating account…" className={AUTH_SUBMIT_CLASSES}>
          Create account
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
