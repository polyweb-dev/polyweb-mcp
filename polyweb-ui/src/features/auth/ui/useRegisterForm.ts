import { useState } from "react"
import type { FormEvent } from "react"
import { authErrorText, registerAccount } from "@/domains/auth"
import type { UserAccount } from "@/domains/auth"
import { registerFieldErrors, validateRegisterForm } from "./registerValidation"
import type { RegisterFieldErrors } from "./registerValidation"

const REGISTER_FAILURE =
  "Registration failed. Check the email address, the profile fields, and the password rule."

export type RegisterProfileField = "email" | "username" | "firstName" | "lastName"

export interface RegisterForm {
  email: string
  username: string
  firstName: string
  lastName: string
  password: string
  confirmation: string
  fieldErrors: RegisterFieldErrors
  error: string | null
  pending: boolean
  created: UserAccount | null
  setPassword: (value: string) => void
  setConfirmation: (value: string) => void
  updateField: (field: RegisterProfileField, value: string) => void
  handleSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>
}

/**
 * Registration draft state, validation, and the public account creation.
 *
 * Blank profile fields are rejected locally with field-level errors; the
 * request submits trimmed values and maps backend validation items back
 * onto their fields. A success clears the password drafts and stores the
 * created account for the confirmation screen.
 */
export function useRegisterForm(): RegisterForm {
  const [email, setEmail] = useState("")
  const [username, setUsername] = useState("")
  const [firstName, setFirstName] = useState("")
  const [lastName, setLastName] = useState("")
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [fieldErrors, setFieldErrors] = useState<RegisterFieldErrors>({})
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [created, setCreated] = useState<UserAccount | null>(null)

  function updateField(field: RegisterProfileField, value: string): void {
    if (field === "email") setEmail(value)
    if (field === "username") setUsername(value)
    if (field === "firstName") setFirstName(value)
    if (field === "lastName") setLastName(value)
    const mapped: keyof RegisterFieldErrors =
      field === "firstName" ? "first_name" : field === "lastName" ? "last_name" : field
    setFieldErrors((previous) => (previous[mapped] ? { ...previous, [mapped]: undefined } : previous))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (pending) return
    const checked = validateRegisterForm({ email, username, firstName, lastName, password, confirmation })
    setFieldErrors(checked.fieldErrors)
    if (checked.problem !== null) {
      setError(checked.problem)
      return
    }
    setPending(true)
    setError(null)
    setFieldErrors({})
    try {
      const account = await registerAccount({
        email: email.trim(),
        password,
        username: username.trim(),
        first_name: firstName.trim(),
        last_name: lastName.trim(),
      })
      setPassword("")
      setConfirmation("")
      setCreated(account)
    } catch (failure) {
      const mapped = registerFieldErrors(failure)
      if (mapped !== null) setFieldErrors(mapped)
      setError(authErrorText(failure, REGISTER_FAILURE))
    } finally {
      setPending(false)
    }
  }

  return {
    email,
    username,
    firstName,
    lastName,
    password,
    confirmation,
    fieldErrors,
    error,
    pending,
    created,
    setPassword,
    setConfirmation,
    updateField,
    handleSubmit,
  }
}
