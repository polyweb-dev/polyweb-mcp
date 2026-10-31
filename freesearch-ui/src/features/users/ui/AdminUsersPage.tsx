import type { FormEvent } from "react"
import { Button } from "@/shared/ui/button"
import { TextField } from "@/shared/ui/TextField"
import { PASSWORD_HINT, useAuth } from "@/domains/auth"
import { SYSTEM_PERMISSIONS, hasPermission, useProjectsOptional } from "@/domains/projects"
import { useAdminUsersController } from "../model/useAdminUsersController"
import { AdminAccountFacts } from "./AdminAccountFacts"

/**
 * Account-creation screen.
 *
 * The screen creates one standalone account from an email and a password
 * through the authenticated provisioning route; there is no role or
 * account-type choice. It shows the safe projection of the account that this
 * request created and nothing about any other account. A caller without
 * `system.settings.write` in the live system access sees no form, so a direct
 * URL cannot reach the creation control.
 */
export function AdminUsersPage() {
  const { account } = useAuth()
  const { systemAccess } = useProjectsOptional()
  const controller = useAdminUsersController()
  const canProvision = hasPermission(systemAccess, SYSTEM_PERMISSIONS.settingsWrite)

  if (account === null || !canProvision) {
    return (
      <section className="flex flex-1 flex-col space-y-4">
        <h2 className="text-[var(--text-strong)]">Accounts</h2>
        <p role="status" className="text-[13px] text-[var(--muted)]">
          This screen is available to system administrators only.
        </p>
      </section>
    )
  }

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <header className="border-b border-[var(--border-subtle)] pb-2">
        <h2 className="text-[var(--text-strong)]">Accounts</h2>
        <p className="mt-0.5 text-[13px] text-[var(--muted)]">
          Create a standalone account for a later project association. This cycle grants no
          authority over an existing account.
        </p>
      </header>

      <form
        className="space-y-4 rounded border border-[var(--border-subtle)] p-4"
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault()
          void controller.create()
        }}
        noValidate
      >
        <TextField
          id="admin-account-email"
          label="Email"
          type="email"
          value={controller.email}
          onChange={controller.setEmail}
          disabled={controller.pending}
          autoComplete="email"
        />
        <TextField
          id="admin-account-password"
          label="Password"
          type="password"
          value={controller.password}
          onChange={controller.setPassword}
          disabled={controller.pending}
          autoComplete="new-password"
          hint={PASSWORD_HINT}
        />
        <TextField
          id="admin-account-confirmation"
          label="Confirm password"
          type="password"
          value={controller.confirmation}
          onChange={controller.setConfirmation}
          disabled={controller.pending}
          autoComplete="new-password"
        />
        <Button type="submit" disabled={controller.pending}>
          {controller.pending ? "Creating account" : "Create account"}
        </Button>
      </form>

      {controller.error !== null && (
        <p
          role="alert"
          className="rounded border border-[var(--status-danger)]/40 px-2.5 py-2 text-[13px]"
          style={{ color: "var(--status-danger)" }}
        >
          {controller.error}
        </p>
      )}

      {controller.created !== null && (
        <div className="space-y-3">
          <p
            role="status"
            className="rounded border border-[var(--border-subtle)] px-2.5 py-2 text-[13px]"
          >
            Created the account {controller.created.email}.
          </p>
          <AdminAccountFacts account={controller.created} />
        </div>
      )}
    </section>
  )
}
