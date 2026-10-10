import type { UserAccount } from "@/domains/auth"

function factRow(label: string, value: string) {
  return (
    <div className="rounded border border-[var(--border-subtle)] px-3 py-2">
      <dt className="text-[12px] text-[var(--muted)]">{label}</dt>
      <dd className="text-[13px] text-[var(--text)] tnum">{value}</dd>
    </div>
  )
}

/** Safe account facts of one created account. */
export function AdminAccountFacts({ account }: { account: UserAccount }) {
  return (
    <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {factRow("Email", account.email)}
      {factRow("Account id", account.id)}
      {factRow("Role", account.role)}
      {factRow("Active", account.is_active ? "Active" : "Inactive")}
      {factRow("Verification", account.is_verified ? "Verified" : "Not verified")}
    </dl>
  )
}
