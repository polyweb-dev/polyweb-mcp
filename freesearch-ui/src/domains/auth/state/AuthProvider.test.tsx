import { StrictMode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AuthProvider } from "@/domains/auth/state/AuthProvider"
import { useAuth } from "@/domains/auth/state/useAuth"
import { getAccessToken } from "@/shared/api/session"
import { deferred, err, installFetchStub, ok } from "@/test/fetchMock"
import {
  installFakeChannel,
  installImmediateLocks,
  removeLocks,
} from "@/test/browserStubs"
import {
  RENEWED_ACCESS_TOKEN,
  TEST_ACCESS_TOKEN,
  accessResponseFixture,
  adminAccountFixture,
  developerAccountFixture,
} from "@/test/authFixtures"

const CREDENTIALS = { email: "ada@example.com", password: "s3cret-pw" }
const NETWORK_FAILURE =
  "API unreachable; check the Vite proxy and backend server: network down"

function Probe() {
  const { status, account, error, login, logout, restore } = useAuth()
  return (
    <div>
      <div data-testid="status">{status}</div>
      <div data-testid="account">{account === null ? "none" : account.email}</div>
      <div data-testid="error">{error ?? "no-error"}</div>
      <button type="button" onClick={() => void login(CREDENTIALS)}>
        sign-in
      </button>
      <button type="button" onClick={() => void logout()}>
        sign-out
      </button>
      <button type="button" onClick={() => void restore()}>
        retry
      </button>
    </div>
  )
}

function renderProbe() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  )
}

function installSuccessStub() {
  return installFetchStub((req) => {
    if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
      return ok(accessResponseFixture())
    }
    if (req.url === "/users/me" && req.method === "GET") {
      return ok(adminAccountFixture())
    }
    if (req.url === "/auth/jwt/refresh" && req.method === "DELETE") {
      return new Response(null, { status: 204 })
    }
    return err(404, { detail: "unhandled test route" })
  })
}

function statusText(): string {
  return screen.getByTestId("status").textContent ?? ""
}

function accountText(): string {
  return screen.getByTestId("account").textContent ?? ""
}

beforeEach(() => {
  installImmediateLocks()
  installFakeChannel()
})

afterEach(() => {
  vi.unstubAllGlobals()
  removeLocks()
})

describe("AuthProvider restore", () => {
  it("reaches authenticated with the me account after a successful restore", async () => {
    installSuccessStub()
    renderProbe()

    await waitFor(() => expect(statusText()).toBe("authenticated"))

    expect(accountText()).toBe("admin@example.com")
    expect(getAccessToken()).toBe(TEST_ACCESS_TOKEN)
  })

  it("reaches anonymous when the refresh cookie is rejected with 401", async () => {
    const stub = installFetchStub((req) => {
      if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
        return err(401, { detail: "invalid refresh credential" })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderProbe()

    await waitFor(() => expect(statusText()).toBe("anonymous"))

    expect(accountText()).toBe("none")
    expect(stub.requestsTo("/users/me")).toHaveLength(0)
    expect(getAccessToken()).toBeNull()
  })

  it("reaches unavailable on a network failure and restores on retry", async () => {
    let refreshCalls = 0
    installFetchStub((req) => {
      if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
        refreshCalls += 1
        if (refreshCalls === 1) throw new TypeError("network down")
        return ok(accessResponseFixture())
      }
      if (req.url === "/users/me" && req.method === "GET") {
        return ok(adminAccountFixture())
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderProbe()

    await waitFor(() => expect(statusText()).toBe("unavailable"))
    expect(screen.getByTestId("error").textContent).toBe(NETWORK_FAILURE)
    expect(refreshCalls).toBe(1)

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "retry" }))

    await waitFor(() => expect(statusText()).toBe("authenticated"))
    expect(refreshCalls).toBe(2)
    expect(accountText()).toBe("admin@example.com")
  })

  it("performs one logical restore under a StrictMode double-mount", async () => {
    const stub = installSuccessStub()
    render(
      <StrictMode>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </StrictMode>
    )

    await waitFor(() => expect(statusText()).toBe("authenticated"))

    expect(accountText()).toBe("admin@example.com")
    expect(stub.requestsTo("/auth/jwt/refresh")).toHaveLength(1)
    expect(stub.requestsTo("/users/me")).toHaveLength(1)
  })

  it("shows the friendly configuration state when the secret is missing", async () => {
    installFetchStub((req) => {
      if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
        return err(503, { detail: "account authentication is not configured" })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderProbe()

    await waitFor(() => expect(statusText()).toBe("unavailable"))

    expect(screen.getByTestId("error").textContent).toBe(
      "Sign-in is not ready yet. Set FREESEARCH_AUTH_JWT_SECRET on the server, then restart the API."
    )
    expect(accountText()).toBe("none")
  })

  it("shows the friendly validation text for a serialized restore body", async () => {
    installFetchStub((req) => {
      if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
        return err(422, { detail: "invalid authentication request" })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderProbe()

    await waitFor(() => expect(statusText()).toBe("unavailable"))

    expect(screen.getByTestId("error").textContent).toBe(
      "Check the email address and the password rule."
    )
  })
})

describe("AuthProvider login and logout", () => {
  it("sets authenticated with the fresh account after login", async () => {
    let loggedIn = false
    const stub = installFetchStub((req) => {
      if (req.url === "/auth/jwt/login" && req.method === "POST") {
        loggedIn = true
        return ok(accessResponseFixture({ access_token: RENEWED_ACCESS_TOKEN }))
      }
      if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
        return ok(accessResponseFixture())
      }
      if (req.url === "/users/me" && req.method === "GET") {
        return ok(loggedIn ? developerAccountFixture() : adminAccountFixture())
      }
      if (req.url === "/auth/jwt/refresh" && req.method === "DELETE") {
        return new Response(null, { status: 204 })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderProbe()
    await waitFor(() => expect(statusText()).toBe("authenticated"))
    expect(accountText()).toBe("admin@example.com")

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "sign-in" }))

    await waitFor(() => expect(accountText()).toBe("developer@example.com"))
    expect(statusText()).toBe("authenticated")
    expect(stub.requestsTo("/auth/jwt/login")).toHaveLength(1)
    expect(getAccessToken()).toBe(RENEWED_ACCESS_TOKEN)
  })

  it("returns to anonymous after logout", async () => {
    const stub = installSuccessStub()
    renderProbe()
    await waitFor(() => expect(statusText()).toBe("authenticated"))

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "sign-out" }))

    await waitFor(() => expect(statusText()).toBe("anonymous"))
    expect(accountText()).toBe("none")
    expect(
      stub.requests.filter(
        (req) => req.url === "/auth/jwt/refresh" && req.method === "DELETE"
      )
    ).toHaveLength(1)
    expect(getAccessToken()).toBeNull()
  })

  it("holds no memory credential when logout wins over a pending restore", async () => {
    const gate = deferred<Response>()
    const stub = installFetchStub((req) => {
      if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
        return gate.promise
      }
      if (req.url === "/auth/jwt/refresh" && req.method === "DELETE") {
        return new Response(null, { status: 204 })
      }
      if (req.url === "/users/me" && req.method === "GET") {
        return ok(adminAccountFixture())
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderProbe()
    await waitFor(() =>
      expect(stub.requestsTo("/auth/jwt/refresh")).toHaveLength(1)
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "sign-out" }))
    await waitFor(() => expect(statusText()).toBe("anonymous"))

    gate.resolve(ok(accessResponseFixture({ access_token: RENEWED_ACCESS_TOKEN })))
    await gate.promise
    await waitFor(() => expect(stub.requestsTo("/users/me")).toHaveLength(1))
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(statusText()).toBe("anonymous")
    expect(accountText()).toBe("none")
    expect(getAccessToken()).toBeNull()
  })

  it("never installs the account when logout wins over a pending restore", async () => {
    const gate = deferred<Response>()
    const stub = installFetchStub((req) => {
      if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
        return gate.promise
      }
      if (req.url === "/auth/jwt/refresh" && req.method === "DELETE") {
        return new Response(null, { status: 204 })
      }
      if (req.url === "/users/me" && req.method === "GET") {
        return ok(adminAccountFixture())
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderProbe()
    await waitFor(() =>
      expect(stub.requestsTo("/auth/jwt/refresh")).toHaveLength(1)
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "sign-out" }))
    await waitFor(() => expect(statusText()).toBe("anonymous"))

    gate.resolve(ok(accessResponseFixture()))
    await gate.promise
    await waitFor(() => expect(stub.requestsTo("/users/me")).toHaveLength(1))
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(statusText()).toBe("anonymous")
    expect(accountText()).toBe("none")
  })
})
