import { Link } from "react-router"
import { ROLE_LABELS } from "@/domains/auth"
import type { UserRole } from "@/domains/auth"
import { LOGIN_PATH } from "@/app/routes"
import { AUTH_FOOTER_CLASSES, AUTH_FOOTER_TEXT_CLASSES, AUTH_LINK_CLASSES, AuthPanel } from "./AuthPanel"

/** Confirmation of one created account, with its stored role and no credential. */
export function RegisterSuccess({ role }: { role: UserRole }) {
  return (
    <AuthPanel title="Account created" subtitle={`Your ${ROLE_LABELS[role]} account is ready.`}>
      <p role="status" className="text-[13px] text-[var(--text)]">
        Sign in with the email address and password that you just registered.
      </p>
      <div className={AUTH_FOOTER_CLASSES}>
        <p className={AUTH_FOOTER_TEXT_CLASSES}>
          <Link to={LOGIN_PATH} className={AUTH_LINK_CLASSES}>
            Go to sign in
          </Link>
        </p>
      </div>
    </AuthPanel>
  )
}
