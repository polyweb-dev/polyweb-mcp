import { useState } from "react"
import type { FormEvent } from "react"
import { Link, Navigate, useNavigate, useSearchParams } from "react-router"
import { Button } from "@/shared/ui/button"
import { authErrorText, useAuth } from "@/domains/auth"
import { REGISTER_PATH, returnDestination } from "@/app/routes"
import {
  AUTH_FOOTER_CLASSES,
  AUTH_FOOTER_TEXT_CLASSES,
  AUTH_LINK_CLASSES,
  AUTH_SUBMIT_CLASSES,
  AuthPanel,
} from "./AuthPanel"
import { TextField } from "@/shared/ui/TextField"

const LOGIN_FAILURE = "Sign-in failed. Check your email address and password."

/**
 * Login screen.
 *
 * The OAuth2 form posts the email as `username`. A successful login keeps the
 * access credential in memory and installs the refresh cookie. The screen
 * accepts a return destination only from the internal route set, disables a
 * duplicate submit, and clears the password draft after a successful submit.
 */
export function LoginPage() {
  const { login, status, account } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const destination = returnDestination(params.get("returnTo"))

  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  if (status === "authenticated" && account !== null) {
    return <Navigate to={destination} replace />
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (pending) return
    setPending(true)
    setError(null)
    try {
      await login({ email, password })
      setPassword("")
      navigate(destination, { replace: true })
    } catch (failure) {
      setError(authErrorText(failure, LOGIN_FAILURE))
    } finally {
      setPending(false)
    }
  }

  return (
    <AuthPanel title="Sign in">
      <form className="space-y-6" onSubmit={(event) => void handleSubmit(event)} noValidate>
        <div className="space-y-4">
          <TextField
            id="login-email"
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            disabled={pending}
            autoComplete="email"
          />
          <TextField
            id="login-password"
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            disabled={pending}
            autoComplete="current-password"
          />
        </div>
        {error !== null && (
          <p
            role="alert"
            className="rounded border border-[var(--status-danger)]/40 px-2.5 py-2 text-[13px]"
            style={{ color: "var(--status-danger)" }}
          >
            {error}
          </p>
        )}
        <Button type="submit" size="form" disabled={pending} className={AUTH_SUBMIT_CLASSES}>
          {pending ? "Signing in" : "Sign in"}
        </Button>
      </form>
      <div className={AUTH_FOOTER_CLASSES}>
        <p className={AUTH_FOOTER_TEXT_CLASSES}>
          No account yet?{" "}
          <Link to={REGISTER_PATH} className={AUTH_LINK_CLASSES}>
            Create an account
          </Link>
        </p>
      </div>
    </AuthPanel>
  )
}
