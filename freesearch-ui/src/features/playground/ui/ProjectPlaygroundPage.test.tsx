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
  projectProviderType,
  projectProvidersFixture,
  searchResponseFixture,
} from "@/test/backendFixtures"
import { PlaygroundHarness } from "@/test/renderPlayground"
import { PLAYGROUND_PROJECT_ID, projectProvidersUrl } from "@/test/projectPlayground"
import { playgroundPersistKey } from "@/store/playgroundPersistence"

type Handler = (req: RecordedRequest) => Response | Promise<Response> | null

function stub(handler: Handler = () => null) {
  return installFetchStub((req) => {
    const answered = handler(req)
    if (answered !== null) return answered
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

async function submitSearch(query: string) {
  const input = (await screen.findByPlaceholderText(/Search across all providers/i)) as HTMLInputElement
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

    await waitFor(async () => {
      expect(await openPicker("playground-search-provider")).toEqual([
        "Auto",
        "All providers",
        "Brave Search",
        "You.com",
      ])
    })
  })

  it("offers only Auto and All providers without providers.read, with no view request", async () => {
    const fetchStub = stub()
    const permissions = PROJECT_MEMBER_PERMISSIONS.filter((p) => p !== "providers.read")
    render(<PlaygroundHarness permissions={permissions} />)

    expect(await openPicker("playground-search-provider")).toEqual(["Auto", "All providers"])
    expect(fetchStub.requestsTo(projectProvidersUrl())).toHaveLength(0)
  })

  it("disables the Fetch mode without fetch.execute", async () => {
    stub()
    render(<PlaygroundHarness permissions={["project.read", "search.execute"]} />)

    const fetchTab = await screen.findByRole("tab", { name: "Fetch" })
    expect(fetchTab).toHaveAttribute("aria-disabled", "true")
    expect(screen.getByRole("tab", { name: "Search" })).not.toHaveAttribute("aria-disabled", "true")
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
      /Search across all providers/i
    )) as HTMLInputElement
    expect(input.value).toBe("")
    expect(screen.queryByText("Live backend result one")).not.toBeInTheDocument()
    expect(
      window.localStorage.getItem(playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_BETA_ID)) ?? ""
    ).not.toContain("Live backend result one")
    expect(within(document.body).queryByText(/Executing/)).not.toBeInTheDocument()
  })
})
