import { accountDisplayName, useAuth } from "@/domains/auth"
import type { UserAccount } from "@/domains/auth"
import { identityLabel } from "@/shared/lib/identity"
import type { Fact } from "@/shared/ui/FactList"
import { PageHeader } from "@/shared/ui/PageHeader"

const SIGN_IN_METHODS: Record<UserAccount["auth_provider"], string> = {
  local: "Email and password",
  workos: "Single sign-on",
}

/**
 * Account view: one card of facts from `GET /users/me`. A signed-in account
 * is active by definition, so no status row. Verification has no supported
 * action and is omitted. The full name leads when one exists, then the
 * username, with the email kept for contact and sign-in context. Sign out
 * lives in the sidebar account popup.
 */
export function AccountPage() {
  const { account } = useAuth()
  if (account === null) return null
  const name = accountDisplayName(account)
  const username = account.username !== null && account.username.trim() !== "" ? account.username.trim() : null
  const facts: Fact[] = [
    { label: "Email", value: account.email },
    ...(name === null ? [] : [{ label: "Name", value: identityLabel(account) }]),
    ...(username === null || username === name ? [] : [{ label: "Username", value: username }]),
    { label: "Sign-in method", value: SIGN_IN_METHODS[account.auth_provider] },
  ]

  return (
    <section className="flex flex-1 flex-col">
      <PageHeader title="Account" description="The account you are signed in with" />
      <dl aria-label="Account" className="fs-panel grid grid-cols-2 gap-4 p-4">
        {facts.map((fact) => (
          <div key={fact.label} className="min-w-0 space-y-1 text-[13px]">
            <dt className="text-[var(--muted)]">{fact.label}</dt>
            <dd className="m-0 break-words text-[var(--text-strong)]">{fact.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
