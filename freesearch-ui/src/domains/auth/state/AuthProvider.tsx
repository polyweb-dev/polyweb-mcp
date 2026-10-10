import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"
import { ApiError } from "@/shared/api/http"
import {
  configureAuthTransport,
  setAccessToken,
  subscribeSessionChanges,
} from "@/shared/api/session"
import {
  getMe,
  login as loginRequest,
  logout as logoutRequest,
  refreshAccess,
} from "../api/authApi"
import { AuthContext } from "./context"
import type { AuthContextValue } from "./context"
import { authErrorText } from "../model/authErrorText"
import type { AuthCredentials, AuthState } from "../model/types"

const RESTORE_FAILURE = "The account session could not be restored. Check the connection."

const RESTORING: AuthState = { status: "restoring", account: null, error: null }
const ANONYMOUS: AuthState = { status: "anonymous", account: null, error: null }

function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

/**
 * Session owner of the browser client.
 *
 * The provider restores the session from the refresh cookie, confirms the
 * account with `GET /users/me`, and installs the cookie policy of the shared
 * transport. One generation counter cancels stale tasks, so a late response can
 * never install a credential or an account after a logout or a new login. The
 * bootstrap runs once per mount, which keeps React StrictMode idempotent.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(RESTORING)
  const epochRef = useRef(0)
  const startedRef = useRef(false)

  const invalidate = useCallback(() => {
    epochRef.current += 1
    setState(ANONYMOUS)
  }, [])

  const restore = useCallback(async () => {
    const epoch = epochRef.current + 1
    epochRef.current = epoch
    setState(RESTORING)
    try {
      await refreshAccess()
      const account = await getMe()
      if (epochRef.current !== epoch) {
        // A logout or a new login won the race: drop any late credential.
        setAccessToken(null)
        return
      }
      setState({ status: "authenticated", account, error: null })
    } catch (error) {
      if (epochRef.current !== epoch) {
        setAccessToken(null)
        return
      }
      if (isUnauthorized(error)) {
        setState(ANONYMOUS)
        return
      }
      setState({
        status: "unavailable",
        account: null,
        error: authErrorText(error, RESTORE_FAILURE),
      })
    }
  }, [])

  const login = useCallback(async (credentials: AuthCredentials) => {
    const epoch = epochRef.current + 1
    epochRef.current = epoch
    await loginRequest(credentials)
    const account = await getMe()
    if (epochRef.current !== epoch) {
      // A logout or another login won the race: drop any late credential.
      setAccessToken(null)
      return
    }
    setState({ status: "authenticated", account, error: null })
  }, [])

  const logout = useCallback(async () => {
    epochRef.current += 1
    try {
      await logoutRequest()
    } finally {
      setState(ANONYMOUS)
    }
  }, [])

  // The shared transport refreshes through this provider, so a 401 on an
  // ordinary call renews the credential and a lost session clears the UI.
  useEffect(
    () => configureAuthTransport({ refresh: refreshAccess, invalidate }),
    [invalidate]
  )

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    void restore()
  }, [restore])

  useEffect(() => subscribeSessionChanges(invalidate), [invalidate])

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, logout, restore }),
    [state, login, logout, restore]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
