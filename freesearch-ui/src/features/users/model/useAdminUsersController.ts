import { useCallback, useState } from "react"
import { authErrorText, provisionAccount } from "@/domains/auth"
import type { UserAccount, UserRole } from "@/domains/auth"

const CREATE_FAILURE = "The account could not be created. Check the email address and the password rule."

/**
 * Controller of the Admin account-creation screen.
 *
 * The screen creates one standalone account in the selected role and shows the
 * safe projection of that new account. It holds no authority over an existing
 * account, so it never loads a target and never changes a stored role. The
 * caller's own session, credential, and store stay unchanged.
 */
export interface AdminUsersController {
  email: string
  password: string
  confirmation: string
  roleDraft: UserRole
  pending: boolean
  created: UserAccount | null
  error: string | null
  setEmail: (value: string) => void
  setPassword: (value: string) => void
  setConfirmation: (value: string) => void
  setRoleDraft: (value: UserRole) => void
  create: () => Promise<void>
}

export function useAdminUsersController(): AdminUsersController {
  const [email, setEmailState] = useState("")
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [roleDraft, setRoleDraft] = useState<UserRole>("agent")
  const [pending, setPending] = useState(false)
  const [created, setCreated] = useState<UserAccount | null>(null)
  const [error, setError] = useState<string | null>(null)

  const setEmail = useCallback((value: string) => {
    setEmailState(value)
    setCreated(null)
    setError(null)
  }, [])

  const setRoleDraftValue = useCallback((value: UserRole) => {
    setRoleDraft(value)
    setCreated(null)
  }, [])

  const create = useCallback(async () => {
    if (pending) return
    if (!email.trim()) {
      setError("Enter an email address.")
      return
    }
    if (password !== confirmation) {
      setError("The two passwords do not match.")
      return
    }
    setPending(true)
    setError(null)
    try {
      const account = await provisionAccount({ email, password, role: roleDraft })
      setPassword("")
      setConfirmation("")
      setCreated(account)
    } catch (failure) {
      setError(authErrorText(failure, CREATE_FAILURE))
    } finally {
      setPending(false)
    }
  }, [pending, email, password, confirmation, roleDraft])

  return {
    email,
    password,
    confirmation,
    roleDraft,
    pending,
    created,
    error,
    setEmail,
    setPassword,
    setConfirmation,
    setRoleDraft: setRoleDraftValue,
    create,
  }
}
