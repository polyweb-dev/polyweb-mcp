import { describe, it, expect } from "vitest"
import { ApiError } from "@/shared/api/http"
import { authErrorText } from "./authErrorText"

const RULE =
  "Use 12 to 128 characters with an upper-case letter, a lower-case letter, a digit, and a symbol."
const DUPLICATE = "That email address already has an account. Sign in instead."
const BAD_CREDENTIALS = "The email address or the password is not correct."
const INVALID_REQUEST = "Check the email address and the password rule."
const SESSION_ENDED = "Your session ended. Sign in again."
const REJECTED = "This request was rejected. Reload the page and try again."
const NOT_CONFIGURED =
  "Sign-in is not ready yet. Set POLYWEB_AUTH_JWT_SECRET on the server, then restart the API."
const UNAVAILABLE = "The account service is unavailable. Try again in a moment."
const FALLBACK = "Registration failed. Check the email address and the password rule."

function codeError(code: string, status: number, detail: string): ApiError {
  return new ApiError(status, detail, { detail: { code, reason: "test-reason" } })
}

describe("authErrorText", () => {
  it("maps REGISTER_INVALID_PASSWORD to the rule sentence", () => {
    const error = codeError(
      "REGISTER_INVALID_PASSWORD",
      400,
      '{"detail":{"code":"REGISTER_INVALID_PASSWORD"}}'
    )

    expect(authErrorText(error, FALLBACK)).toBe(RULE)
  })

  it("maps REGISTER_USER_ALREADY_EXISTS to the duplicate sentence", () => {
    const error = new ApiError(
      400,
      "REGISTER_USER_ALREADY_EXISTS",
      { detail: { code: "REGISTER_USER_ALREADY_EXISTS" } }
    )

    expect(authErrorText(error, FALLBACK)).toBe(DUPLICATE)
  })

  it("maps LOGIN_BAD_CREDENTIALS to the bad-credentials sentence", () => {
    const error = new ApiError(400, "LOGIN_BAD_CREDENTIALS", {
      detail: "LOGIN_BAD_CREDENTIALS",
    })

    expect(authErrorText(error, "Sign-in failed. Check your email address and password.")).toBe(
      BAD_CREDENTIALS
    )
  })

  it("maps a raw code string body to its friendly sentence", () => {
    const error = new ApiError(400, "LOGIN_BAD_CREDENTIALS", "LOGIN_BAD_CREDENTIALS")

    expect(authErrorText(error, FALLBACK)).toBe(BAD_CREDENTIALS)
  })

  it("maps the safe validation detail to the email and password sentence", () => {
    const error = new ApiError(422, "invalid authentication request", {
      detail: "invalid authentication request",
    })

    expect(authErrorText(error, FALLBACK)).toBe(INVALID_REQUEST)
  })

  it("maps the 401 detail to the session-ended sentence", () => {
    const error = new ApiError(401, "not authenticated", { detail: "not authenticated" })

    expect(authErrorText(error, FALLBACK)).toBe(SESSION_ENDED)
  })

  it("maps the browser rejection detail to the reload sentence", () => {
    const error = new ApiError(403, "browser request rejected", {
      detail: "browser request rejected",
    })

    expect(authErrorText(error, FALLBACK)).toBe(REJECTED)
  })

  it("maps the unconfigured detail to the operator action sentence", () => {
    const error = new ApiError(503, "account authentication is not configured", {
      detail: "account authentication is not configured",
    })

    expect(authErrorText(error, FALLBACK)).toBe(NOT_CONFIGURED)
  })

  it("maps the unavailable detail to the retry sentence", () => {
    const error = new ApiError(503, "authentication is temporarily unavailable", {
      detail: "authentication is temporarily unavailable",
    })

    expect(authErrorText(error, FALLBACK)).toBe(UNAVAILABLE)
  })

  it("shows no raw JSON for a serialized register body", () => {
    const serialized =
      '{"detail":{"code":"REGISTER_INVALID_PASSWORD","reason":"Password should contain a digit."}}'
    const error = new ApiError(400, serialized, {
      detail: { code: "REGISTER_INVALID_PASSWORD", reason: "Password should contain a digit." },
    })

    const text = authErrorText(error, FALLBACK)

    expect(text).toBe(RULE)
    expect(text).not.toContain("REGISTER_INVALID_PASSWORD")
    expect(text).not.toContain("{")
    expect(text).not.toContain("reason")
  })

  it("maps a serialized 401 body to the session status sentence", () => {
    const error = new ApiError(401, '{"detail":{"unexpected":1}}', {
      detail: { unexpected: 1 },
    })

    expect(authErrorText(error, FALLBACK)).toBe(SESSION_ENDED)
  })

  it("maps a serialized 403 body to the rejection status sentence", () => {
    const error = new ApiError(403, '{"detail":{"unexpected":1}}', {
      detail: { unexpected: 1 },
    })

    expect(authErrorText(error, FALLBACK)).toBe(REJECTED)
  })

  it("maps a serialized 422 body to the validation status sentence", () => {
    const error = new ApiError(422, '[{"loc":["body","email"],"msg":"bad"}]', [
      { loc: ["body", "email"], msg: "bad" },
    ])

    expect(authErrorText(error, FALLBACK)).toBe(INVALID_REQUEST)
  })

  it("maps a serialized 500 body to the unavailable status sentence", () => {
    const error = new ApiError(500, '{"detail":{"unexpected":1}}', {
      detail: { unexpected: 1 },
    })

    expect(authErrorText(error, FALLBACK)).toBe(UNAVAILABLE)
  })

  it("returns the fallback for an unknown object code with no status sentence", () => {
    const error = new ApiError(400, '{"detail":{"code":"FUTURE_CODE"}}', {
      detail: { code: "FUTURE_CODE" },
    })

    expect(authErrorText(error, FALLBACK)).toBe(FALLBACK)
  })

  it("keeps the 429 wait hint verbatim", () => {
    const detail = "too many authentication attempts Try again in 30 seconds."
    const error = new ApiError(429, detail, { detail: "too many authentication attempts" })

    expect(authErrorText(error, FALLBACK)).toBe(detail)
  })

  it("keeps the singular 429 wait hint verbatim", () => {
    const detail = "too many registration attempts Try again in 1 second."
    const error = new ApiError(429, detail, { detail: "too many registration attempts" })

    expect(authErrorText(error, FALLBACK)).toBe(detail)
  })

  it("passes an unknown safe plain sentence through unchanged", () => {
    const error = new ApiError(400, "Email already registered", {
      detail: "Email already registered",
    })

    expect(authErrorText(error, FALLBACK)).toBe("Email already registered")
  })

  it("keeps a plain Error message without the fallback", () => {
    expect(authErrorText(new Error("Invalid credentials for test"), FALLBACK)).toBe(
      "Invalid credentials for test"
    )
  })

  it("returns the fallback for an unknown value without a message", () => {
    expect(authErrorText(null, FALLBACK)).toBe(FALLBACK)
    expect(authErrorText(undefined, FALLBACK)).toBe(FALLBACK)
  })
})
