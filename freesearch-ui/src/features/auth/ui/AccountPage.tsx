import { Link } from "react-router"
import { ROLE_LABELS, useAuth } from "@/domains/auth"
import { TAB_PATHS } from "@/app/routes"

/**
 * Account status view.
 *
 * Every value comes from `GET /users/me`. The screen shows no access token, no
 * refresh credential, and no session family identifier, and it offers the Admin
 * link to an Admin account only. Sign out lives in the sidebar account popup.
 */
export function AccountPage() {
  const { account } = useAuth()
  if (account === null) return null

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <header className="flex flex-col gap-4 border-b border-[var(--border-subtle)] pb-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-[var(--text-strong)]">Account</h2>
          <p className="mt-0.5 text-[13px] text-[var(--muted)]">
            The identity and the role of this session.
          </p>
        </div>
        {account.role === "admin" && (
          <Link
            to={TAB_PATHS.adminUsers}
            className="text-[13px] underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]"
          >
            Create accounts
          </Link>
        )}
      </header>

      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded border border-[var(--border-subtle)] px-3 py-2">
          <dt className="text-[12px] text-[var(--muted)]">Email</dt>
          <dd className="text-[13px] text-[var(--text)]">{account.email}</dd>
        </div>
        <div className="rounded border border-[var(--border-subtle)] px-3 py-2">
          <dt className="text-[12px] text-[var(--muted)]">Account id</dt>
          <dd className="text-[13px] text-[var(--text)] tnum">{account.id}</dd>
        </div>
        <div className="rounded border border-[var(--border-subtle)] px-3 py-2">
          <dt className="text-[12px] text-[var(--muted)]">Role</dt>
          <dd className="text-[13px] text-[var(--text)]">{ROLE_LABELS[account.role]}</dd>
        </div>
        <div className="rounded border border-[var(--border-subtle)] px-3 py-2">
          <dt className="text-[12px] text-[var(--muted)]">Active</dt>
          <dd className="text-[13px] text-[var(--text)]">
            {account.is_active ? "Active" : "Inactive"}
          </dd>
        </div>
        <div className="rounded border border-[var(--border-subtle)] px-3 py-2">
          <dt className="text-[12px] text-[var(--muted)]">Verification</dt>
          <dd className="text-[13px] text-[var(--text)]">
            {account.is_verified ? "Verified" : "Not verified"}
          </dd>
        </div>
      </dl>

      <p className="text-[12px] text-[var(--muted)]">
        Session credentials stay in memory and in one strict cookie. This page never shows a
        credential.
      </p>
    </section>
  )
}
