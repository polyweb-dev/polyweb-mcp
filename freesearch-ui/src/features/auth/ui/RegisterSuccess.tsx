import { Link } from "react-router"
import { LOGIN_PATH } from "@/app/routes"
import { AUTH_FOOTER_CLASSES, AUTH_FOOTER_TEXT_CLASSES, AUTH_LINK_CLASSES, AuthPanel } from "./AuthPanel"

/** Confirmation of one created account, with no credential and no role text. */
export function RegisterSuccess() {
  return (
    <AuthPanel title="Account created" subtitle="Your account is ready.">
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
