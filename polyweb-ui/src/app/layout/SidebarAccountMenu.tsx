import { useState } from "react"
import { Popover as PopoverPrimitive } from "@base-ui/react/popover"
import { LogOut, UserRound } from "lucide-react"
import { Link } from "react-router"
import { cn } from "cn"
import { accountDisplayName, authErrorText, useAuth } from "@/domains/auth"
import { MENU_ITEM_CLASS, MENU_SEPARATOR_CLASS } from "@/shared/ui/menuStyles"
import { TAB_PATHS } from "../routes"

const SIGN_OUT_FAILURE = "Sign out failed. Try again."

/** One letter of the text avatar: the display name's, else the email's. */
function avatarLetter(name: string | null, email: string): string {
  return (name ?? email).trim().slice(0, 1).toUpperCase() || "?"
}

/**
 * Identity lines of the account row and popup: the display name above the
 * email when the account has a name or username, else the email alone.
 */
function identityLines(name: string | null, email: string) {
  return (
    <span className="flex min-w-0 flex-col text-left">
      <span className="truncate text-[13px] font-medium text-[var(--text-strong)]">
        {name ?? email}
      </span>
      {name !== null && (
        <span className="truncate text-[11px] text-[var(--muted)]">{email}</span>
      )}
    </span>
  )
}

/**
 * Sign out action of the account popup with its pending and error states.
 *
 * The action stays disabled while the logout promise waits. The error line
 * shows safe text only.
 */
function renderSignOutAction(
  pending: boolean,
  error: string | null,
  onSignOut: () => void
) {
  return (
    <>
      <button
        type="button"
        onClick={() => void onSignOut()}
        disabled={pending}
        className={MENU_ITEM_CLASS}
      >
        <LogOut aria-hidden="true" className="text-[var(--muted)]" strokeWidth={1.75} />
        <span>Sign out</span>
      </button>

      {error !== null && (
        <p role="alert" className="px-2 pb-2 pt-1 text-[12px] text-[var(--status-danger)]">
          {error}
        </p>
      )}
    </>
  )
}

interface SidebarAccountMenuProps {
  collapsed: boolean
}

/**
 * Account row of the sidebar foot and its account popover.
 *
 * One inset divider sits above the whole expanded account row. The row shows
 * the email, with the full name or username above it when the account has
 * one; no role text appears. The popup holds Account and Sign out; it repeats
 * the identity only for the collapsed avatar row, which shows no email. The
 * component reads the
 * safe account projection and the logout action from the auth barrel; it holds
 * no credential, and it renders nothing without a confirmed account.
 */
export function SidebarAccountMenu({ collapsed }: SidebarAccountMenuProps) {
  const { account, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (account === null) return null

  const name = accountDisplayName(account)

  /** One accepted Sign out action on the current logout seam. */
  async function handleSignOut(): Promise<void> {
    if (pending) return
    setPending(true)
    setError(null)
    try {
      await logout()
      setOpen(false)
    } catch (reason) {
      setError(authErrorText(reason, SIGN_OUT_FAILURE))
    } finally {
      setPending(false)
    }
  }

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen} modal={false}>
      {/* The divider sits before the entire avatar-and-text row and outside the
          trigger, so the row stays one button, both ends keep a visible gap,
          and the collapsed avatar-only row holds no rule. */}
      {!collapsed && (
        <div aria-hidden="true" className="mx-2 mb-2 h-px bg-[var(--border-subtle)]" />
      )}

      <PopoverPrimitive.Trigger
        type="button"
        aria-label="Open user menu"
        title={collapsed ? account.email : undefined}
        className={cn(
          "flex h-10 w-full items-center rounded-md text-[13px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--raised)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] aria-expanded:bg-[var(--raised)] motion-reduce:transition-none",
          collapsed ? "justify-center px-0" : "gap-2.5 px-2"
        )}
      >
        <span
          aria-hidden="true"
          className="grid size-7 shrink-0 place-items-center rounded-full border border-[var(--border-subtle)] bg-[var(--raised)] text-[11px] font-semibold leading-none text-[var(--text-strong)]"
        >
          {avatarLetter(name, account.email)}
        </span>
        {!collapsed && identityLines(name, account.email)}
      </PopoverPrimitive.Trigger>

      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Positioner
          side="top"
          align="start"
          sideOffset={8}
          className="z-60 outline-none"
        >
          <PopoverPrimitive.Popup
            // The first Escape closes this popup only: the drawer keeps its
            // own document listener and must not consume the same key press.
            onKeyDown={(event) => {
              if (open && event.key === "Escape") event.stopPropagation()
            }}
            className="w-56 max-w-[calc(100vw-1rem)] rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] p-1.5 text-[var(--text)] shadow-lg outline-none"
          >
            <PopoverPrimitive.Title className="sr-only">User account</PopoverPrimitive.Title>

            {collapsed && (
              <>
                <div className="flex items-center gap-3 px-2 py-2">
                  <span
                    aria-hidden="true"
                    className="grid size-10 shrink-0 place-items-center rounded-full border border-[var(--border-subtle)] bg-[var(--secondary)] text-[13px] font-semibold leading-none text-[var(--text-strong)]"
                  >
                    {avatarLetter(name, account.email)}
                  </span>
                  {identityLines(name, account.email)}
                </div>
                <div className={MENU_SEPARATOR_CLASS} />
              </>
            )}

            <Link to={TAB_PATHS.account} className={MENU_ITEM_CLASS} onClick={() => setOpen(false)}>
              <UserRound aria-hidden="true" className="text-[var(--muted)]" strokeWidth={1.75} />
              <span>Account</span>
            </Link>
            {renderSignOutAction(pending, error, handleSignOut)}
          </PopoverPrimitive.Popup>
        </PopoverPrimitive.Positioner>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
