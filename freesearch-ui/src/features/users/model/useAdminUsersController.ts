import { useCallback, useState } from "react"
import { authErrorText, passwordLengthProblem, provisionAccount } from "@/domains/auth"
import type { UserAccount } from "@/domains/auth"

const CREATE_FAILURE = "The account could not be created. Check the email address and the password rule."

/**
 * Controller of the account-creation screen.
 *
 * The screen creates one standalone account from an email and a password only
 * and shows the safe projection of that new account. There is no role or
 * account-type choice: authority comes from explicit assignments. It never
 * loads an existing account. The caller's own session, credential, and store
 * stay unchanged.
 */
export interface AdminUsersController {
  email: string
  password: string
  confirmation: string
  pending: boolean
  created: UserAccount | null
  error: string | null
  setEmail: (value: string) => void
  setPassword: (value: string) => void
  setConfirmation: (value: string) => void
  create: () => Promise<void>
}

export function useAdminUsersController(): AdminUsersController {
  const [email, setEmailState] = useState("")
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [pending, setPending] = useState(false)
  const [created, setCreated] = useState<UserAccount | null>(null)
  const [error, setError] = useState<string | null>(null)

  const setEmail = useCallback((value: string) => {
    setEmailState(value)
    setCreated(null)
    setError(null)
  }, [])

  const create = useCallback(async () => {
    if (pending) return
    if (!email.trim()) {
      setError("Enter an email address.")
      return
    }
    const lengthProblem = passwordLengthProblem(password)
    if (lengthProblem !== null) {
      setError(lengthProblem)
      return
    }
    if (password !== confirmation) {
      setError("The two passwords do not match.")
      return
    }
    setPending(true)
    setError(null)
    try {
      const account = await provisionAccount({ email, password })
      setPassword("")
      setConfirmation("")
      setCreated(account)
    } catch (failure) {
      setError(authErrorText(failure, CREATE_FAILURE))
    } finally {
      setPending(false)
    }
  }, [pending, email, password, confirmation])

  return {
    email,
    password,
    confirmation,
    pending,
    created,
    error,
    setEmail,
    setPassword,
    setConfirmation,
    create,
  }
}
