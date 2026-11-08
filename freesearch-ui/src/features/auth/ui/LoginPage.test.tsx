import { describe, it, expect, afterEach, vi } from "vitest"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { UserEvent } from "@testing-library/user-event"
import { useLocation } from "react-router"
import { ApiError } from "@/shared/api/http"
import type { UserAccount } from "@/domains/auth/model/types"
import { LoginPage } from "./LoginPage"
import { renderAuthenticated } from "@/test/renderAuthenticated"
import { adminAccountFixture } from "@/test/authFixtures"

afterEach(() => {
  vi.unstubAllGlobals()
})

const EMAIL = "developer@example.com"
const PASSWORD = "correct-horse-battery-99"

/** Visible pathname probe. The login screen stays mounted, so the test can read the cleared password draft. */
function LocationProbe() {
  const location = useLocation()
  return <p data-testid="location-probe">{location.pathname}</p>
}

function renderLogin(route: string, account: UserAccount | null) {
  return renderAuthenticated(
    <>
      <LoginPage />
      <LocationProbe />
    </>,
    { account, route },
  )
}

async function fillCredentials(user: UserEvent, email: string, password: string): Promise<void> {
  await user.type(screen.getByLabelText("Email"), email)
  await user.type(screen.getByLabelText("Password"), password)
}

describe("LoginPage", () => {
  it("renders the two sign-in fields without redundant helper copy", () => {
    renderLogin("/login", null)

    expect(screen.getByLabelText("Email")).toBeInTheDocument()
    expect(screen.getByLabelText("Password")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument()
    expect(screen.queryByText("Use your FreeSearch account.")).toBeNull()
  })

  it("submits the typed email and password to login", async () => {
    const user = userEvent.setup()
    const { login } = renderLogin("/login", null)

    await fillCredentials(user, EMAIL, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    await screen.findByText("/", { selector: '[data-testid="location-probe"]' })
    expect(login).toHaveBeenCalledTimes(1)
    expect(login).toHaveBeenCalledWith({ email: EMAIL, password: PASSWORD })
  })

  it("disables the submit while pending and blocks a duplicate submit", async () => {
    const user = userEvent.setup()
    const { login } = renderLogin("/login", null)
    login.mockImplementation(() => new Promise<void>(() => {}))

    await fillCredentials(user, EMAIL, PASSWORD)
    const submit = screen.getByRole("button", { name: "Sign in" })
    await user.click(submit)

    const pending = await screen.findByRole("button", { name: "Signing in" })
    expect(pending).toBeDisabled()
    await user.click(pending)
    expect(login).toHaveBeenCalledTimes(1)
  })

  it("shows a safe alert when login fails", async () => {
    const user = userEvent.setup()
    const { login } = renderLogin("/login", null)
    login.mockImplementation(() => Promise.reject(new Error("Invalid credentials for test")))

    await fillCredentials(user, EMAIL, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("Invalid credentials for test")
    expect(screen.getByLabelText("Email")).toBeInTheDocument()
  })

  it("clears the password field and navigates to the workspace entry on success", async () => {
    const user = userEvent.setup()
    const { login } = renderLogin("/login", null)

    await fillCredentials(user, EMAIL, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    await screen.findByText("/", { selector: '[data-testid="location-probe"]' })
    expect(login).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId("location-probe")).toHaveTextContent(/^\/$/)
    expect(screen.getByLabelText("Password")).toHaveValue("")
  })

  it("navigates to the returnTo destination on success", async () => {
    const user = userEvent.setup()
    renderLogin("/login?returnTo=/activity", null)

    await fillCredentials(user, EMAIL, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    await screen.findByText("/activity")
    expect(screen.getByTestId("location-probe")).toHaveTextContent("/activity")
    expect(screen.queryByText("/", { selector: '[data-testid="location-probe"]' })).toBeNull()
  })

  it("falls back to the workspace entry for a foreign returnTo value", async () => {
    const user = userEvent.setup()
    renderLogin("/login?returnTo=https://evil.example.com", null)

    await fillCredentials(user, EMAIL, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    await screen.findByText("/", { selector: '[data-testid="location-probe"]' })
    expect(screen.getByTestId("location-probe")).toHaveTextContent(/^\/$/)
    expect(screen.queryByText("https://evil.example.com")).toBeNull()
  })

  it("shows the wait hint when login hits the attempt limit", async () => {
    const user = userEvent.setup()
    const { login } = renderLogin("/login", null)
    login.mockImplementation(() =>
      Promise.reject(
        new ApiError(
          429,
          "too many authentication attempts Try again in 30 seconds.",
          null
        )
      )
    )

    await fillCredentials(user, EMAIL, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent(
      "too many authentication attempts Try again in 30 seconds."
    )
  })

  it("shows the friendly text for bad credentials without raw JSON", async () => {
    const user = userEvent.setup()
    const { login } = renderLogin("/login", null)
    login.mockImplementation(() =>
      Promise.reject(
        new ApiError(400, "LOGIN_BAD_CREDENTIALS", { detail: "LOGIN_BAD_CREDENTIALS" })
      )
    )

    await fillCredentials(user, EMAIL, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("The email address or the password is not correct.")
    expect(alert.textContent ?? "").not.toContain("LOGIN_BAD_CREDENTIALS")
    expect(alert.textContent ?? "").not.toContain("{")
  })

  it("shows the friendly configuration state when the secret is missing", async () => {
    const user = userEvent.setup()
    const { login } = renderLogin("/login", null)
    login.mockImplementation(() =>
      Promise.reject(
        new ApiError(503, "account authentication is not configured", {
          detail: "account authentication is not configured",
        })
      )
    )

    await fillCredentials(user, EMAIL, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent(
      "Sign-in is not ready yet. Set FREESEARCH_AUTH_JWT_SECRET on the server, then restart the API."
    )
    expect(alert.textContent ?? "").not.toContain("{")
  })

  it("shows the repository brand with one page title", () => {
    renderLogin("/login", null)

    expect(screen.getByText("FreeSearch", { exact: true })).toBeInTheDocument()
    expect(screen.getAllByRole("heading")).toHaveLength(1)
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument()
  })

  it("links to the registration screen", () => {
    renderLogin("/login", null)

    const link = screen.getByRole("link", { name: "Create an account" })
    expect(link).toHaveAttribute("href", "/register")
  })

  it("redirects a pre-authenticated account away from the login form", async () => {
    renderLogin("/login", adminAccountFixture())

    await screen.findByText("/", { selector: '[data-testid="location-probe"]' })
    expect(screen.getByTestId("location-probe")).toHaveTextContent(/^\/$/)
    expect(screen.queryByLabelText("Email")).toBeNull()
  })
})
