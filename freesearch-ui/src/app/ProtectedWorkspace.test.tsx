import { useEffect } from "react"
import type { ReactElement } from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { screen, waitFor, render } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router"
import { ProtectedWorkspace } from "./ProtectedWorkspace"
import { AuthContext } from "@/domains/auth/state/context"
import {
  authenticatedContextValue,
  renderAuthenticated,
} from "@/test/renderAuthenticated"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import {
  allProvidersFixture,
  dashboardFixture,
  routingConfigFixture,
} from "@/test/backendFixtures"
import {
  adminAccountFixture,
  developerAccountFixture,
} from "@/test/authFixtures"
import type { UserAccount } from "@/domains/auth"

function stubWorkspace() {
  return installFetchStub((req) => {
    if (req.method === "GET" && req.url === "/api/v1/providers") {
      return ok(allProvidersFixture())
    }
    if (req.method === "GET" && req.url === "/api/v1/routing/config") {
      return ok(routingConfigFixture())
    }
    if (req.method === "GET" && req.url.startsWith("/dashboard")) {
      return ok(dashboardFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
}

function LocationProbe() {
  const location = useLocation()
  return (
    <div data-testid="location">{`${location.pathname}${location.search}`}</div>
  )
}

let workspaceMounts = 0

function MountProbe() {
  useEffect(() => {
    workspaceMounts += 1
  }, [])
  return <div>Workspace ready</div>
}

function rerenderWorkspace(
  rerender: (ui: ReactElement) => void,
  account: UserAccount | null,
) {
  rerender(
    <MemoryRouter initialEntries={["/"]}>
      <AuthContext.Provider value={authenticatedContextValue(account)}>
        <ProtectedWorkspace>
          <MountProbe />
        </ProtectedWorkspace>
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe("ProtectedWorkspace", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the restore status without the workspace while restoring", () => {
    renderAuthenticated(
      <ProtectedWorkspace>
        <div>Workspace ready</div>
      </ProtectedWorkspace>,
      { status: "restoring" },
    )

    expect(screen.getByText("Restoring your session")).toBeInTheDocument()
    expect(screen.queryByText("Workspace ready")).toBeNull()
  })

  it("shows the retry view and retries the restore on click", async () => {
    const rendered = renderAuthenticated(
      <ProtectedWorkspace>
        <div>Workspace ready</div>
      </ProtectedWorkspace>,
      { status: "unavailable", account: null },
    )

    expect(
      screen.getByText("The account session is unavailable"),
    ).toBeInTheDocument()
    expect(
      screen.getByText("The account session could not be restored."),
    ).toBeInTheDocument()
    expect(screen.queryByText("Workspace ready")).toBeNull()

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Retry" }))
    expect(rendered.restore).toHaveBeenCalledTimes(1)
  })

  it("navigates an anonymous visitor to the login page", async () => {
    renderAuthenticated(
      <>
        <ProtectedWorkspace>
          <div>Workspace ready</div>
        </ProtectedWorkspace>
        <LocationProbe />
      </>,
      { account: null, route: "/" },
    )

    await waitFor(() => {
      expect(screen.getByTestId("location").textContent).toBe("/login")
    })
    expect(screen.queryByText("Workspace ready")).toBeNull()
  })

  it("mounts the workspace children for an authenticated account", async () => {
    stubWorkspace()
    renderAuthenticated(
      <ProtectedWorkspace>
        <div>Workspace ready</div>
      </ProtectedWorkspace>,
    )

    await waitFor(() => {
      expect(screen.getByText("Workspace ready")).toBeInTheDocument()
    })
  })

  it("remounts the workspace when the account switches", async () => {
    stubWorkspace()
    workspaceMounts = 0
    const rendered = renderAuthenticated(
      <ProtectedWorkspace>
        <MountProbe />
      </ProtectedWorkspace>,
      { account: adminAccountFixture() },
    )

    await waitFor(() => {
      expect(screen.getByText("Workspace ready")).toBeInTheDocument()
    })
    expect(workspaceMounts).toBe(1)

    rerenderWorkspace(rendered.rerender, developerAccountFixture())

    await waitFor(() => {
      expect(workspaceMounts).toBe(2)
    })
    expect(screen.getByText("Workspace ready")).toBeInTheDocument()
  })

  it("preserves the deep link destination in the login redirect", async () => {
    render(
      <MemoryRouter initialEntries={["/activity"]}>
        <AuthContext.Provider value={authenticatedContextValue(null)}>
          <Routes>
            <Route
              path="/activity"
              element={
                <ProtectedWorkspace>
                  <div>Workspace ready</div>
                </ProtectedWorkspace>
              }
            />
            <Route path="/login" element={<LocationProbe />} />
          </Routes>
        </AuthContext.Provider>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId("location").textContent).toBe(
        "/login?returnTo=%2Factivity",
      )
    })
    expect(screen.queryByText("Workspace ready")).toBeNull()
  })

  it("preserves the former project keys destination through login", async () => {
    const projectId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    render(
      <MemoryRouter initialEntries={[`/p/${projectId}/settings?tab=keys`]}>
        <AuthContext.Provider value={authenticatedContextValue(null)}>
          <Routes>
            <Route path="/login" element={<LocationProbe />} />
            <Route path="*" element={<ProtectedWorkspace><div>Workspace ready</div></ProtectedWorkspace>} />
          </Routes>
        </AuthContext.Provider>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(
      `/login?returnTo=${encodeURIComponent(`/p/${projectId}/providers`)}`,
    ))
  })

  it.each(["/settings?tab=keys", "/system/providers?tab=credentials"])(
    "preserves the destination of anonymous legacy keys link %s",
    async (route) => {
      render(
        <MemoryRouter initialEntries={[route]}>
          <AuthContext.Provider value={authenticatedContextValue(null)}>
            <Routes>
              <Route path="/login" element={<LocationProbe />} />
              <Route path="*" element={<ProtectedWorkspace><div>Workspace ready</div></ProtectedWorkspace>} />
            </Routes>
          </AuthContext.Provider>
        </MemoryRouter>,
      )
      await waitFor(() => {
        expect(screen.getByTestId("location")).toHaveTextContent("/login?returnTo=%2Faccount%2Fkeys")
      })
    },
  )
})
