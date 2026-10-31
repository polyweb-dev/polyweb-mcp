import { Link } from "react-router"
import { accountDisplayName, useAuth } from "@/domains/auth"
import { SYSTEM_PERMISSIONS, hasPermission, useProjectsOptional } from "@/domains/projects"
import { TAB_PATHS } from "@/app/routes"

function fact(label: string, value: string, numeric = false) {
  return (
    <div className="rounded border border-[var(--border-subtle)] px-3 py-2">
      <dt className="text-[12px] text-[var(--muted)]">{label}</dt>
      <dd className={numeric ? "text-[13px] text-[var(--text)] tnum" : "text-[13px] text-[var(--text)]"}>
        {value}
      </dd>
    </div>
  )
}

/**
 * Account status view.
 *
 * Every value comes from `GET /users/me`. The screen shows no access token, no
 * refresh credential, no session family identifier, and no role. The account
 * creation link appears only when the live system access grants
 * `system.settings.write`. Sign out lives in the sidebar account popup.
 */
export function AccountPage() {
  const { account } = useAuth()
  const { systemAccess } = useProjectsOptional()
  if (account === null) return null
  const name = accountDisplayName(account)

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <header className="flex flex-col gap-4 border-b border-[var(--border-subtle)] pb-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-[var(--text-strong)]">Account</h2>
          <p className="mt-0.5 text-[13px] text-[var(--muted)]">
            The identity of this session.
          </p>
        </div>
        {hasPermission(systemAccess, SYSTEM_PERMISSIONS.settingsWrite) && (
          <Link
            to={TAB_PATHS.adminUsers}
            className="text-[13px] underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]"
          >
            Create accounts
          </Link>
        )}
      </header>

      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {fact("Email", account.email)}
        {name !== null && fact("Name", name)}
        {fact("Account id", account.id, true)}
        {fact("Active", account.is_active ? "Active" : "Inactive")}
        {fact("Verification", account.is_verified ? "Verified" : "Not verified")}
      </dl>

      <p className="text-[12px] text-[var(--muted)]">
        Session credentials stay in memory and in one strict cookie. This page never shows a
        credential.
      </p>
    </section>
  )
}
