import { useCallback, useState } from "react"
import type { NewCredentialInput } from "@/domains/providers"
import type { ActionStatus } from "./useActionStatus"
import {
  ROTATE_FAILED_MESSAGE,
  SAVE_FAILED_MESSAGE,
  credentialFailureMessage,
  keySavedNotice,
} from "./credentialMessages"
import type { CredentialRef, CredentialRoutes } from "./credentialRoutes"

export interface CredentialForms {
  /** Failure inside the open add or rotate form. */
  formError: string | null
  adding: boolean
  openAdd: (open: boolean) => void
  create: (input: NewCredentialInput) => Promise<boolean>
  rotating: CredentialRef | null
  openRotate: (credential: CredentialRef | null) => void
  rotate: (secret: string) => Promise<boolean>
}

export interface AddKeyFormControl {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Add and rotate forms of one credential list. The secret passes straight
 * from the form into one request and never enters this hook's state.
 */
export function useCredentialForms(
  routes: CredentialRoutes,
  reload: () => void,
  status: ActionStatus,
  addForm?: AddKeyFormControl
): CredentialForms {
  const { begin, finish } = status
  const [formError, setFormError] = useState<string | null>(null)
  const [localAdding, setLocalAdding] = useState(false)
  const adding = addForm?.open ?? localAdding
  const setAdding = addForm?.onOpenChange ?? setLocalAdding
  const [rotating, setRotating] = useState<CredentialRef | null>(null)

  const create = useCallback(
    async (input: NewCredentialInput) => {
      begin()
      setFormError(null)
      try {
        await routes.create(input)
        setAdding(false)
        finish({ notice: keySavedNotice(input.label) })
        reload()
        return true
      } catch (error) {
        finish()
        setFormError(credentialFailureMessage(error, SAVE_FAILED_MESSAGE))
        return false
      }
    },
    [begin, finish, routes, reload, setAdding]
  )

  const rotate = useCallback(
    async (secret: string) => {
      const target = rotating
      if (target === null) return false
      begin()
      setFormError(null)
      try {
        await routes.rotate(target.id, target.generation ?? 1, secret)
        setRotating(null)
        finish({ notice: keySavedNotice(target.label) })
        reload()
        return true
      } catch (error) {
        finish()
        setFormError(credentialFailureMessage(error, ROTATE_FAILED_MESSAGE, true))
        return false
      }
    },
    [begin, finish, rotating, routes, reload]
  )

  const openAdd = useCallback((open: boolean) => {
    setFormError(null)
    setAdding(open)
  }, [setAdding])

  const openRotate = useCallback((credential: CredentialRef | null) => {
    setFormError(null)
    setRotating(credential)
  }, [])

  return { formError, adding, openAdd, create, rotating, openRotate, rotate }
}
