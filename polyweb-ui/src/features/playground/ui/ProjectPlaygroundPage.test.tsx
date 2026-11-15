import { afterEach, describe, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { deferred, err, installFetchStub, ok } from "@/test/fetchMock"
import type { RecordedRequest } from "@/test/fetchMock"
import {
  PROJECT_BETA_ID,
  PROJECT_MEMBER_PERMISSIONS,
} from "@/test/accessFixtures"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
import {
  SUCCESS_TRACE_ID,
  projectProviderType,
  projectProvidersFixture,
  searchResponseFixture,
  traceDetailFixture,
} from "@/test/backendFixtures"
import { PlaygroundHarness } from "@/test/renderPlayground"
import { PLAYGROUND_PROJECT_ID, projectProvidersUrl } from "@/test/projectPlayground"
import { playgroundPersistKey } from "@/store/playgroundPersistence"

type Handler = (req: RecordedRequest) => Response | Promise<Response> | null

function orderFixture(search: string[], fetch: string[] = search, notAllowed: string[] = []) {
  const operation = (ids: string[], excluded: string[] = []) => ({
    strategy: "custom",
    providers: ids.map((provider) => ({ provider, name: provider, call_cost_usd: null, keyless: false })),
    has_saved_custom: true,
    not_allowed: excluded,
  })
  return { revision: 1, search: operation(search, notAllowed), fetch: operation(fetch) }
}

function stub(handler: Handler = () => null) {
  return installFetchStub((req) => {
    const answered = handler(req)
    if (answered !== null) return answered
    if (req.method === "GET" && req.url.endsWith("/routing/order")) {
      return ok(orderFixture(["brave", "you"], ["you"]))
    }
    if (req.method === "GET" && req.url.endsWith("/providers")) {
      const projectId = req.url.split("/")[4] ?? ""
      return ok(projectProvidersFixture(projectId))
    }
    if (req.url === "/search" && req.method === "POST") return ok(searchResponseFixture())
    return err(404, { detail: "unhandled test route" })
  })
}

async function openPicker(testId: string): Promise<string[]> {
  const trigger = await screen.findByTestId(testId)
  fireEvent.click(trigger)
  const options = await screen.findAllByRole("option")
  return options.map((option) => option.textContent?.trim() ?? "")
}

async function expectPicker(testId: string, expected: string[]) {
  fireEvent.click(await screen.findByTestId(testId))
  await waitFor(() => {
    expect(screen.getAllByRole("option").map((option) => option.textContent?.trim() ?? "")).toEqual(expected)
  })
}

async function submitSearch(query: string) {
  const input = (await screen.findByPlaceholderText(/Search the web/i)) as HTMLInputElement
  fireEvent.change(input, { target: { value: query } })
  fireEvent.submit(input.closest("form") as HTMLFormElement)
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
  window.sessionStorage.clear()
})

describe("ProjectPlaygroundPage provider picker", () => {
  it("offers Auto, All providers, then the project's search providers by catalog name", async () => {
    stub((req) =>
      req.url === projectProvidersUrl()
        ? ok(
            projectProvidersFixture(PLAYGROUND_PROJECT_ID, [
              projectProviderType("brave"),
              projectProviderType("you"),
              projectProviderType("exa", []),
            ])
          )
        : null
    )
    render(<PlaygroundHarness />)

    await expectPicker("playground-search-provider", ["Auto", "All providers", "Brave Search", "You.com"])
  })

  it("uses separate project orders and excludes providers that are off for the operation", async () => {
    stub((req) => {
      if (req.url.endsWith("/routing/order")) {
        return ok(orderFixture(["you", "keenable", "brave"], ["keenable", "you"], ["keenable"]))
      }
      if (req.url === projectProvidersUrl()) {
        return ok(projectProvidersFixture(PLAYGROUND_PROJECT_ID, [
          projectProviderType("brave"),
          projectProviderType("you", []),
          projectProviderType("keenable"),
        ]))
      }
      return null
    })
    render(<PlaygroundHarness />)
    await expectPicker("playground-search-provider", [
      "Auto", "All providers", "You.com", "Brave Search",
    ])
    fireEvent.click(screen.getByRole("tab", { name: "Fetch" }))
    expect(await openPicker("playground-fetch-provider")).toEqual(["Auto", "Keenable", "You.com"])
  })

  it("offers only Auto and All providers without providers.read, with no view request", async () => {
    const fetchStub = stub()
    const permissions = PROJECT_MEMBER_PERMISSIONS.filter((p) => p !== "providers.read")
    render(<PlaygroundHarness permissions={permissions} />)

    expect(await openPicker("playground-search-provider")).toEqual(["Auto", "All providers"])
    expect(fetchStub.requestsTo(projectProvidersUrl())).toHaveLength(0)
    expect(fetchStub.requestsTo(`/api/v1/projects/${PLAYGROUND_PROJECT_ID}/routing/order`)).toHaveLength(0)
  })

  it("disables the Fetch mode without fetch.execute", async () => {
    stub()
    render(<PlaygroundHarness permissions={["project.read", "search.execute"]} />)

    const fetchTab = await screen.findByRole("tab", { name: "Fetch" })
    expect(fetchTab).toHaveAttribute("aria-disabled", "true")
    expect(screen.getByRole("tab", { name: "Search" })).not.toHaveAttribute("aria-disabled", "true")
  })
})

describe("ProjectPlaygroundPage provider read states", () => {
  it("offers retry when the project order cannot be read", async () => {
    let reads = 0
    stub((req) => {
      if (!req.url.endsWith("/routing/order")) return null
      reads += 1
      return reads === 1 ? err(503, null) : ok(orderFixture(["brave"], []))
    })
    render(<PlaygroundHarness />)
    expect(await screen.findByText(/Couldn't load this project's providers/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    await expectPicker("playground-search-provider", ["Auto", "All providers", "Brave Search"])
  })

  it("shows the setup notice and disables submit while no provider can run the mode", async () => {
    stub((req) => {
      if (req.url.endsWith("/routing/order")) return ok(orderFixture([], []))
      return req.url === projectProvidersUrl()
        ? ok(projectProvidersFixture(PLAYGROUND_PROJECT_ID, [projectProviderType("brave", [])]))
        : null
    })
    render(<PlaygroundHarness />)

    expect(
      await screen.findByText(/No provider is set up for this project/)
    ).toBeInTheDocument()
    const setupLink = screen.getByRole("link", { name: "Set up providers" })
    expect(setupLink).toHaveAttribute("href", `/p/${PLAYGROUND_PROJECT_ID}/providers`)
    expect(await screen.findByRole("button", { name: "Search" })).toBeDisabled()
  })

  it("shows an error with a working Retry when the provider read fails", async () => {
    let calls = 0
    const fetchStub = stub((req) => {
      if (req.url !== projectProvidersUrl()) return null
      calls += 1
      return calls === 1
        ? err(503, { detail: "provider view down" })
        : ok(
            projectProvidersFixture(PLAYGROUND_PROJECT_ID, [
              projectProviderType("brave"),
              projectProviderType("you"),
            ])
          )
    })
    render(<PlaygroundHarness />)

    expect(
      await screen.findByText(/Couldn't load this project's providers/)
    ).toBeInTheDocument()
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }))

    await expectPicker("playground-search-provider", ["Auto", "All providers", "Brave Search", "You.com"])
    expect(fetchStub.requestsTo(projectProvidersUrl()).length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText(/Couldn't load this project's providers/)).toBeNull()
  })

  it("shows no setup notice and keeps submit enabled without providers.read", async () => {
    const fetchStub = stub()
    const permissions = PROJECT_MEMBER_PERMISSIONS.filter((p) => p !== "providers.read")
    render(<PlaygroundHarness permissions={permissions} />)

    expect(await screen.findByRole("button", { name: "Search" })).toBeEnabled()
    expect(fetchStub.requestsTo(projectProvidersUrl())).toHaveLength(0)
    expect(screen.queryByText(/No provider is set up for this project/)).toBeNull()
    expect(screen.queryByRole("link", { name: "Set up providers" })).toBeNull()
  })

  it("maps a backend no-provider 503 to the setup notice instead of the raw message", async () => {
    stub((req) =>
      req.url === "/search" && req.method === "POST"
        ? err(503, { detail: "no provider is configured for this project" })
        : null
    )
    render(<PlaygroundHarness />)

    await submitSearch("anything")
    expect(
      await screen.findByText(/No provider is set up for this project/)
    ).toBeInTheDocument()
    expect(screen.queryByText(/API temporarily unavailable/)).toBeNull()
  })
})

describe("ProjectPlaygroundPage project execution", () => {
  it("sends project_id on the human session and never stores an API key", async () => {
    const fetchStub = stub()
    render(<PlaygroundHarness />)

    await submitSearch("project query")
    await screen.findByText("Live backend result one")

    const [search] = fetchStub.requestsTo("/search")
    expect(search?.body).toMatchObject({
      project_id: PLAYGROUND_PROJECT_ID,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
    for (const value of Object.values(search?.headers ?? {})) {
      expect(value).not.toContain("fs_live_")
    }
    expect(Object.keys(search?.headers ?? {}).map((key) => key.toLowerCase())).not.toContain(
      "x-api-key"
    )
    await waitFor(() => {
      expect(
        window.localStorage.getItem(playgroundPersistKey(ADMIN_ACCOUNT_ID, PLAYGROUND_PROJECT_ID))
      ).toContain("project query")
    })
    const stored = [window.localStorage, window.sessionStorage].flatMap((storage) =>
      Object.keys(storage).map((key) => storage.getItem(key) ?? "")
    )
    expect(stored.join("\n")).not.toContain("fs_live_")
  })

  it("keeps a loading search across a section switch without a duplicate request", async () => {
    const gate = deferred<Response>()
    const fetchStub = stub((req) => (req.url === "/search" ? gate.promise : null))
    const view = render(<PlaygroundHarness />)

    await submitSearch("survivor query")
    await waitFor(() => {
      expect(fetchStub.requestsTo("/search")).toHaveLength(1)
    })
    const signal = fetchStub.requestsTo("/search")[0]?.signal

    view.rerender(<PlaygroundHarness showPage={false} />)
    expect(await screen.findByRole("heading", { name: "Members" })).toBeInTheDocument()
    expect(signal?.aborted).toBe(false)

    view.rerender(<PlaygroundHarness />)
    expect(await screen.findByRole("button", { name: /Executing/ })).toBeDisabled()
    expect(fetchStub.requestsTo("/search")).toHaveLength(1)

    await act(async () => {
      gate.resolve(ok(searchResponseFixture()))
      await gate.promise
    })
    expect(await screen.findByText("Live backend result one")).toBeInTheDocument()
    expect(fetchStub.requestsTo("/search")).toHaveLength(1)
  })

  it("aborts the old project's search on a switch and never renders its result", async () => {
    const gate = deferred<Response>()
    const fetchStub = stub((req) => (req.url === "/search" ? gate.promise : null))
    const view = render(<PlaygroundHarness />)

    await submitSearch("alpha query")
    await waitFor(() => {
      expect(fetchStub.requestsTo("/search")).toHaveLength(1)
    })
    const signal = fetchStub.requestsTo("/search")[0]?.signal

    view.rerender(<PlaygroundHarness projectId={PROJECT_BETA_ID} />)
    expect(signal?.aborted).toBe(true)

    await act(async () => {
      gate.resolve(ok(searchResponseFixture()))
      await gate.promise
    })

    const input = (await screen.findByPlaceholderText(
      /Search the web/i
    )) as HTMLInputElement
    expect(input.value).toBe("")
    expect(screen.queryByText("Live backend result one")).not.toBeInTheDocument()
    expect(
      window.localStorage.getItem(playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_BETA_ID)) ?? ""
    ).not.toContain("Live backend result one")
    expect(within(document.body).queryByText(/Executing/)).not.toBeInTheDocument()
  })
})

/**
 * TASK-000002: View details opens the Activity trace inspector for the call
 * the Playground just made. The trace id is the `X-Trace-Id` header of the
 * search; the detail is read through the project route only, never through a
 * list or a global trace read.
 */
describe("ProjectPlaygroundPage View details", () => {
  const traceUrl = `/api/v1/projects/${PLAYGROUND_PROJECT_ID}/traces/${SUCCESS_TRACE_ID}`

  function tracedSearch(traceId: string | null): Response {
    const headers: Record<string, string> = { "Content-Type": "application/json" }
    if (traceId !== null) headers["X-Trace-Id"] = traceId
    return new Response(JSON.stringify(searchResponseFixture()), { status: 200, headers })
  }

  function traceStub(traceId: string | null, detail: () => Response) {
    return stub((req) => {
      if (req.url === "/search" && req.method === "POST") return tracedSearch(traceId)
      if (req.method === "GET" && req.url === traceUrl) return detail()
      return null
    })
  }

  function traceReads(fetchStub: ReturnType<typeof stub>) {
    return fetchStub.requests.filter((req) => req.url.includes("/traces"))
  }

  async function openDetails() {
    await submitSearch("trace query")
    await screen.findByText("Live backend result one")
    expect(screen.queryByRole("button", { name: /raw JSON/i })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "View details" }))
    return screen.findByRole("dialog")
  }

  it("opens the project trace inspector for the call's trace", async () => {
    const fetchStub = traceStub(SUCCESS_TRACE_ID, () => ok(traceDetailFixture()))
    render(<PlaygroundHarness />)

    const dialog = await openDetails()
    expect(within(dialog).getByText("Trace detail")).toBeInTheDocument()
    expect(await within(dialog).findByText("distributed consensus algorithms")).toBeInTheDocument()
    expect(within(dialog).getAllByText("Consensus algorithms explained").length).toBeGreaterThan(0)
    expect(traceReads(fetchStub).map((req) => req.url)).toEqual([traceUrl])

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }))
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
    expect(screen.getByText("Live backend result one")).toBeInTheDocument()
  })

  it("explains a metadata-only trace instead of showing empty results", async () => {
    traceStub(SUCCESS_TRACE_ID, () => ok(traceDetailFixture({ input: null, output: null })))
    render(<PlaygroundHarness />)

    const dialog = await openDetails()
    expect(await within(dialog).findByText("Metadata only")).toBeInTheDocument()
    expect(within(dialog).getByText("Query not stored")).toBeInTheDocument()
    expect(within(dialog).getAllByText("Results were not stored (metadata-only trace policy)").length).toBeGreaterThan(0)
  })

  it("says the trace is not in this project when the project read answers 404", async () => {
    const fetchStub = traceStub(SUCCESS_TRACE_ID, () => err(404, { detail: "no trace" }))
    render(<PlaygroundHarness />)

    const dialog = await openDetails()
    expect(await within(dialog).findByText("This trace is not available in this project")).toBeInTheDocument()
    expect(traceReads(fetchStub).map((req) => req.url)).toEqual([traceUrl])
  })

  it("explains an untraced call without any trace read", async () => {
    const fetchStub = traceStub(null, () => ok(traceDetailFixture()))
    render(<PlaygroundHarness />)

    const dialog = await openDetails()
    expect(
      within(dialog).getByText("No trace was recorded for this request, so its details are not available")
    ).toBeInTheDocument()
    expect(traceReads(fetchStub)).toHaveLength(0)
  })

  it("explains missing Activity permission without any trace read", async () => {
    const fetchStub = traceStub(SUCCESS_TRACE_ID, () => ok(traceDetailFixture()))
    const permissions = PROJECT_MEMBER_PERMISSIONS.filter((p) => p !== "traces.read")
    render(<PlaygroundHarness permissions={permissions} />)

    const dialog = await openDetails()
    expect(
      within(dialog).getByText("You need permission to read this project's Activity to see these details")
    ).toBeInTheDocument()
    expect(traceReads(fetchStub)).toHaveLength(0)
  })
})
