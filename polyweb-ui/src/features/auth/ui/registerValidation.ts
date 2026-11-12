import { ApiError } from "@/shared/api/http"
import { passwordLengthProblem } from "@/domains/auth"

export type RegisterFieldErrors = Partial<
  Record<"username" | "first_name" | "last_name" | "email", string>
>

const FIELD_LOCATIONS: Record<string, keyof RegisterFieldErrors> = {
  username: "username",
  first_name: "first_name",
  firstName: "first_name",
  last_name: "last_name",
  lastName: "last_name",
  email: "email",
}

/**
 * Return the last body path of one backend validation error, or `null`.
 *
 * FastAPI-style error items carry a `loc` such as `["body", "username"]`.
 */
function validationField(item: unknown): keyof RegisterFieldErrors | null {
  if (typeof item !== "object" || item === null) return null
  const loc = (item as { loc?: unknown }).loc
  if (!Array.isArray(loc)) return null
  for (let index = loc.length - 1; index >= 0; index -= 1) {
    const part = loc[index]
    if (typeof part === "string" && part in FIELD_LOCATIONS) {
      return FIELD_LOCATIONS[part] as keyof RegisterFieldErrors
    }
  }
  return null
}

/**
 * Map one failed registration response onto per-field errors.
 *
 * Object `detail` arrays with FastAPI validation items that name a known
 * form field set that field; everything else falls back to the friendly
 * top-level message.
 */
export function registerFieldErrors(error: unknown): RegisterFieldErrors | null {
  if (!(error instanceof ApiError)) return null
  const raw = error.raw
  if (typeof raw !== "object" || raw === null) return null
  const detail = (raw as { detail?: unknown }).detail
  if (!Array.isArray(detail)) return null
  const errors: RegisterFieldErrors = {}
  for (const item of detail) {
    const field = validationField(item)
    if (field === null || errors[field] !== undefined) continue
    const message =
      typeof item === "object" && item !== null && typeof (item as { msg?: unknown }).msg === "string"
        ? String((item as { msg: string }).msg)
        : "Enter a valid value."
    errors[field] = message
  }
  return Object.keys(errors).length > 0 ? errors : null
}

export interface RegisterFormInput {
  email: string
  username: string
  firstName: string
  lastName: string
  password: string
  confirmation: string
}

/**
 * Reject blank profile fields, then defer to the password rule.
 *
 * Blank means empty or whitespace-only. A missing profile field sets both a
 * field-level error and the top-level alert; the server stays authoritative
 * for the full name and username policy.
 */
export function validateRegisterForm(input: RegisterFormInput): {
  problem: string | null
  fieldErrors: RegisterFieldErrors
} {
  const { email, username, firstName, lastName, password, confirmation } = input
  const fieldErrors: RegisterFieldErrors = {}
  if (!email.trim()) fieldErrors.email = "Enter your email address."
  if (!username.trim()) fieldErrors.username = "Enter a username."
  if (!firstName.trim()) fieldErrors.first_name = "Enter your first name."
  if (!lastName.trim()) fieldErrors.last_name = "Enter your last name."
  if (Object.keys(fieldErrors).length > 0) {
    return { problem: "Enter the missing profile details.", fieldErrors }
  }
  const lengthProblem = passwordLengthProblem(password)
  if (lengthProblem !== null) return { problem: lengthProblem, fieldErrors }
  if (password !== confirmation) return { problem: "The two passwords do not match.", fieldErrors }
  return { problem: null, fieldErrors }
}
