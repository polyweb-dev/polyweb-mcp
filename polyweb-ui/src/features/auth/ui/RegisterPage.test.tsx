import { describe, it, expect, afterEach, vi } from "vitest"
import { fireEvent, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { RegisterPage } from "./RegisterPage"
import { renderAuthenticated } from "@/test/renderAuthenticated"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import { agentAccountFixture } from "@/test/authFixtures"

afterEach(() => {
  vi.unstubAllGlobals()
})

const EMAIL = "new-agent@example.com"
const PASSWORD = "correct-horse-battery-99"
const MISMATCH = "different-horse-battery-11"

function renderRegister() {
  return renderAuthenticated(<RegisterPage />, { account: null, route: "/register" })
}

function stubUnreachable() {
  return installFetchStub(() => err(500, { detail: "fetch must stay unused" }))
}

function fillForm(email: string, password: string, confirmation: string): void {
  if (email !== "") {
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: email } })
  }
  if (password !== "") {
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } })
  }
  if (confirmation !== "") {
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: confirmation },
    })
  }
}

describe("RegisterPage", () => {
  it("renders the three labels and the 12-128 password hint", () => {
    stubUnreachable()
    renderRegister()

    expect(screen.getByLabelText("Email")).toBeInTheDocument()
    expect(screen.getByLabelText("Password")).toBeInTheDocument()
    expect(screen.getByLabelText("Confirm password")).toBeInTheDocument()
    expect(screen.getByText("Use 12 to 128 characters.")).toBeInTheDocument()
  })

  it("offers no role or account-type choice", () => {
    stubUnreachable()
    renderRegister()

    expect(screen.queryByLabelText(/role/i)).toBeNull()
    expect(screen.queryByLabelText(/account type/i)).toBeNull()
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(screen.queryByRole("option")).toBeNull()
    expect(document.body.textContent ?? "").not.toMatch(/\b(Admin|Developer|Agent)\b/)
  })

  it("rejects an empty email address without a fetch", async () => {
    const user = userEvent.setup()
    const stub = stubUnreachable()
    renderRegister()

    fillForm("", PASSWORD, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("Enter your email address.")
    expect(stub.requests).toHaveLength(0)
  })

  it("rejects mismatched passwords without a fetch", async () => {
    const user = userEvent.setup()
    const stub = stubUnreachable()
    renderRegister()

    fillForm(EMAIL, PASSWORD, MISMATCH)
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("The two passwords do not match.")
    expect(stub.requests).toHaveLength(0)
  })

  it("rejects a short password without a fetch", async () => {
    const user = userEvent.setup()
    const stub = stubUnreachable()
    renderRegister()

    fillForm(EMAIL, "short", "short")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Use at least 12 characters for the password.",
    )
    expect(stub.requests).toHaveLength(0)
  })

  it("rejects an overlong password without a fetch", async () => {
    const user = userEvent.setup()
    const stub = stubUnreachable()
    const overlong = "a".repeat(129)
    renderRegister()

    fillForm(EMAIL, overlong, overlong)
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Use no more than 128 characters for the password.",
    )
    expect(stub.requests).toHaveLength(0)
  })

  it("creates the account and sends exactly the email and the password", async () => {
    const user = userEvent.setup()
    const stub = installFetchStub((req) => {
      if (req.url === "/auth/register" && req.method === "POST") {
        return ok(agentAccountFixture({ email: EMAIL }))
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderRegister()

    fillForm(EMAIL, PASSWORD, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(await screen.findByText("Account created")).toBeInTheDocument()
    expect(screen.getByText("Your account is ready.")).toBeInTheDocument()
    const signIn = screen.getByRole("link", { name: "Go to sign in" })
    expect(signIn).toHaveAttribute("href", "/login")
    expect(stub.requests).toHaveLength(1)
    const [only] = stub.requests
    expect(only?.url).toBe("/auth/register")
    expect(only?.method).toBe("POST")
    expect(only?.body).toEqual({ email: EMAIL, password: PASSWORD })
    expect(stub.requests.every((req) => req.url === "/auth/register")).toBe(true)
  })

  it("prevents duplicate account creation while the request is pending", async () => {
    const stub = installFetchStub(() => new Promise<Response>(() => {}))
    renderRegister()
    fillForm(EMAIL, PASSWORD, PASSWORD)
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Create account" }))
    const pending = await screen.findByRole("button", { name: "Creating account…" })
    expect(pending).toBeDisabled()
    expect(pending).toHaveAttribute("aria-busy", "true")
    await user.click(pending)
    expect(stub.requests).toHaveLength(1)
  })

  it("confirms the creation without role text and without automatic login", async () => {
    const user = userEvent.setup()
    const stub = installFetchStub((req) => {
      if (req.url === "/auth/register" && req.method === "POST") {
        return ok(agentAccountFixture({ email: EMAIL }))
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderRegister()

    fillForm(EMAIL, PASSWORD, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(await screen.findByText("Account created")).toBeInTheDocument()
    expect(document.body.textContent ?? "").not.toMatch(/\b(Admin|Developer|Agent)\b/)
    expect(screen.getByRole("link", { name: "Go to sign in" })).toBeInTheDocument()
    expect(stub.requests).toHaveLength(1)
    expect(stub.requests.some((req) => req.url.startsWith("/auth/jwt"))).toBe(false)
  })

  it("shows the safe server message for a duplicate email", async () => {
    const user = userEvent.setup()
    const stub = installFetchStub((req) => {
      if (req.url === "/auth/register" && req.method === "POST") {
        return err(400, { detail: "Email already registered" })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderRegister()

    fillForm(EMAIL, PASSWORD, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("Email already registered")
    expect(stub.requests).toHaveLength(1)
  })

  it("shows the friendly rule without raw JSON for a weak password", async () => {
    const user = userEvent.setup()
    const stub = installFetchStub((req) => {
      if (req.url === "/auth/register" && req.method === "POST") {
        return err(400, {
          detail: {
            code: "REGISTER_INVALID_PASSWORD",
            reason: "Password should contain a digit and a symbol.",
          },
        })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderRegister()

    fillForm(EMAIL, PASSWORD, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent(
      "Use 12 to 128 characters with an upper-case letter, a lower-case letter, a digit, and a symbol."
    )
    expect(alert.textContent ?? "").not.toContain("REGISTER_INVALID_PASSWORD")
    expect(alert.textContent ?? "").not.toContain("{")
    expect(stub.requests).toHaveLength(1)
  })

  it("shows the friendly duplicate text for a coded duplicate email", async () => {
    const user = userEvent.setup()
    installFetchStub((req) => {
      if (req.url === "/auth/register" && req.method === "POST") {
        return err(400, { detail: { code: "REGISTER_USER_ALREADY_EXISTS" } })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderRegister()

    fillForm(EMAIL, PASSWORD, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("That email address already has an account. Sign in instead.")
    expect(alert.textContent ?? "").not.toContain("REGISTER_USER_ALREADY_EXISTS")
  })

  it("shows the friendly configuration state when the secret is missing", async () => {
    const user = userEvent.setup()
    installFetchStub((req) => {
      if (req.url === "/auth/register" && req.method === "POST") {
        return err(503, { detail: "account authentication is not configured" })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderRegister()

    fillForm(EMAIL, PASSWORD, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent(
      "Sign-in is not ready yet. Set POLYWEB_AUTH_JWT_SECRET on the server, then restart the API."
    )
  })

  it("keeps the 429 wait hint on the register screen", async () => {
    const user = userEvent.setup()
    installFetchStub((req) => {
      if (req.url === "/auth/register" && req.method === "POST") {
        return new Response(JSON.stringify({ detail: "too many registration attempts" }), {
          status: 429,
          headers: { "Content-Type": "application/json", "Retry-After": "30" },
        })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderRegister()

    fillForm(EMAIL, PASSWORD, PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("too many registration attempts Try again in 30 seconds.")
  })

  it("shows the repository brand with one page title", () => {
    stubUnreachable()
    renderRegister()

    expect(screen.getByText("Polyweb", { exact: true })).toBeInTheDocument()
    expect(screen.getAllByRole("heading")).toHaveLength(1)
    expect(screen.getByRole("heading", { name: "Create an account" })).toBeInTheDocument()
  })
})
