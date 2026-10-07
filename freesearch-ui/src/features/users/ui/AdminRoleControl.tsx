import { ROLE_LABELS, USER_ROLES } from "@/domains/auth"
import type { UserRole } from "@/domains/auth"

interface AdminRoleControlProps {
  roleDraft: UserRole
  onRoleChange: (role: UserRole) => void
  pending: boolean
}

/** Labeled role select of the Admin account-creation form. */
export function AdminRoleControl({ roleDraft, onRoleChange, pending }: AdminRoleControlProps) {
  return (
    <div>
      <label htmlFor="admin-role" className="block text-[12px] text-[var(--muted)] mb-1">
        Account role
      </label>
      <select
        id="admin-role"
        value={roleDraft}
        onChange={(event) => onRoleChange(event.target.value as UserRole)}
        disabled={pending}
        className="w-full rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1.5 text-[13px] text-[var(--text)] outline-none focus-visible:border-[var(--signal)] disabled:opacity-60"
      >
        {USER_ROLES.map((role) => (
          <option key={role} value={role}>
            {ROLE_LABELS[role]}
          </option>
        ))}
      </select>
    </div>
  )
}
