import { describe, it, expect } from "vitest"
import { ApiError } from "@/shared/api/http"
import { registerFieldErrors, validateRegisterForm } from "./registerValidation"

function fieldError422(field: string): ApiError {
  return new ApiError(422, `${field}: invalid`, {
    detail: [{ loc: ["body", field], msg: `${field} failed`, type: "value_error" }],
  })
}

describe("registerValidation validateRegisterForm", () => {
  it("accepts a complete profile", () => {
    expect(
      validateRegisterForm({
        email: "ada@example.com",
        username: "ada",
        firstName: "Ada",
        lastName: "Lovelace",
        password: "correct-horse-battery-99",
        confirmation: "correct-horse-battery-99",
      })
    ).toEqual({ problem: null, fieldErrors: {} })
  })

  it("rejects each blank profile field with its field error and top-level problem", () => {
    const checked = validateRegisterForm({
      email: "   ",
      username: "",
      firstName: "  ",
      lastName: "",
      password: "correct-horse-battery-99",
      confirmation: "correct-horse-battery-99",
    })
    expect(checked.problem).toBe("Enter the missing profile details.")
    expect(checked.fieldErrors).toEqual({
      email: "Enter your email address.",
      username: "Enter a username.",
      first_name: "Enter your first name.",
      last_name: "Enter your last name.",
    })
  })

  it("checks the password length before the confirmation", () => {
    const checked = validateRegisterForm({
      email: "ada@example.com",
      username: "ada",
      firstName: "Ada",
      lastName: "Lovelace",
      password: "short",
      confirmation: "different",
    })
    expect(checked.problem).toBe("Use at least 12 characters for the password.")
  })

  it("rejects a mismatched confirmation", () => {
    const checked = validateRegisterForm({
      email: "ada@example.com",
      username: "ada",
      firstName: "Ada",
      lastName: "Lovelace",
      password: "correct-horse-battery-99",
      confirmation: "different-horse-battery-11",
    })
    expect(checked.problem).toBe("The two passwords do not match.")
    expect(checked.fieldErrors).toEqual({})
  })
})

describe("registerValidation registerFieldErrors", () => {
  it("maps each FastAPI 422 loc onto its field", () => {
    expect(registerFieldErrors(fieldError422("username"))).toEqual({
      username: "username failed",
    })
    expect(registerFieldErrors(fieldError422("first_name"))).toEqual({
      first_name: "first_name failed",
    })
    expect(registerFieldErrors(fieldError422("last_name"))).toEqual({
      last_name: "last_name failed",
    })
    expect(registerFieldErrors(fieldError422("email"))).toEqual({ email: "email failed" })
  })

  it("maps camelCase loc entries onto their snake_case fields", () => {
    const error = new ApiError(422, "body.firstName: invalid", {
      detail: [{ loc: ["body", "firstName"], msg: "First name failed.", type: "value_error" }],
    })
    expect(registerFieldErrors(error)).toEqual({ first_name: "First name failed." })
  })

  it("keeps the first message per field and ignores unknown fields", () => {
    const error = new ApiError(422, "body: invalid", {
      detail: [
        { loc: ["body", "username"], msg: "First.", type: "value_error" },
        { loc: ["body", "username"], msg: "Second.", type: "value_error" },
        { loc: ["body", "is_superuser"], msg: "Unknown.", type: "value_error" },
      ],
    })
    expect(registerFieldErrors(error)).toEqual({ username: "First." })
  })

  it("returns null for non-field failures", () => {
    expect(registerFieldErrors(new ApiError(400, "Email already registered", null))).toBeNull()
    expect(registerFieldErrors(new Error("boom"))).toBeNull()
    expect(registerFieldErrors(new ApiError(422, "body: invalid", { detail: "invalid" }))).toBeNull()
    expect(registerFieldErrors(new ApiError(422, "body: invalid", { detail: [] }))).toBeNull()
  })
})
