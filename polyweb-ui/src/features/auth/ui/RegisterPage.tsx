import { Link } from "react-router"
import { Button } from "@/shared/ui/button"
import { PASSWORD_HINT } from "@/domains/auth"
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
import { useRegisterForm } from "./useRegisterForm"

/**
 * Registration screen.
 *
 * Public registration creates an ordinary account from the email, the
 * username, the first and last names, and the password only and returns no
 * credential. There is no role or account-type choice: authority comes from
 * explicit system and project assignments. The server stays authoritative for
 * the email and the password rule. The screen confirms the creation and
 * returns to login, and it never signs the new account in automatically.
 */
export function RegisterPage() {
  const form = useRegisterForm()

  if (form.created !== null) return <RegisterSuccess />

  return (
    <AuthPanel title="Create an account" subtitle="Register with your email address.">
      <form className="space-y-4" onSubmit={(event) => void form.handleSubmit(event)} noValidate>
        <TextField
          id="register-email"
          label="Email"
          type="email"
          value={form.email}
          onChange={(value) => form.updateField("email", value)}
          disabled={form.pending}
          autoComplete="email"
          error={form.fieldErrors.email ?? null}
        />
        <TextField
          id="register-username"
          label="Username"
          type="text"
          value={form.username}
          onChange={(value) => form.updateField("username", value)}
          disabled={form.pending}
          autoComplete="username"
          error={form.fieldErrors.username ?? null}
        />
        <TextField
          id="register-first-name"
          label="First name"
          type="text"
          value={form.firstName}
          onChange={(value) => form.updateField("firstName", value)}
          disabled={form.pending}
          autoComplete="given-name"
          error={form.fieldErrors.first_name ?? null}
        />
        <TextField
          id="register-last-name"
          label="Last name"
          type="text"
          value={form.lastName}
          onChange={(value) => form.updateField("lastName", value)}
          disabled={form.pending}
          autoComplete="family-name"
          error={form.fieldErrors.last_name ?? null}
        />
        <TextField
          id="register-password"
          label="Password"
          type="password"
          value={form.password}
          onChange={form.setPassword}
          disabled={form.pending}
          autoComplete="new-password"
          hint={PASSWORD_HINT}
        />
        <TextField
          id="register-confirmation"
          label="Confirm password"
          type="password"
          value={form.confirmation}
          onChange={form.setConfirmation}
          disabled={form.pending}
          autoComplete="new-password"
        />
        {form.error !== null && (
          <p
            role="alert"
            className="rounded border border-[var(--status-danger)]/40 px-2.5 py-2 text-[13px]"
            style={{ color: "var(--status-danger)" }}
          >
            {form.error}
          </p>
        )}
        <Button
          type="submit"
          pending={form.pending}
          pendingLabel="Creating account…"
          className={AUTH_SUBMIT_CLASSES}
        >
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
