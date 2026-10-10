import { ROLE_LABELS, USER_ROLES } from "@/domains/auth"
import type { UserRole } from "@/domains/auth"
import { AUTH_FIELD_CLASSES } from "./AuthPanel"

interface RoleFieldProps {
  role: UserRole
  onChange: (role: UserRole) => void
  disabled: boolean
}

/** Labeled native role select of the registration form. */
export function RoleField({ role, onChange, disabled }: RoleFieldProps) {
  return (
    <div>
      <label htmlFor="register-role" className="block text-[12px] text-[var(--muted)] mb-1">
        Role
      </label>
      <select
        id="register-role"
        value={role}
        onChange={(event) => onChange(event.target.value as UserRole)}
        disabled={disabled}
        className={AUTH_FIELD_CLASSES}
      >
        {USER_ROLES.map((value) => (
          <option key={value} value={value}>
            {ROLE_LABELS[value]}
          </option>
        ))}
      </select>
    </div>
  )
}
