import { afterEach, describe, expect, it, vi } from "vitest"
import { decodeProjectProviders, getProjectProviders } from "./projectProvidersApi"
import { providersForOperation } from "../model/projectProviders"
import { installFetchStub, ok } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID } from "@/test/accessFixtures"
import { projectProviderType, projectProvidersFixture } from "@/test/backendFixtures"

describe("projectProvidersApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("reads the project view route and forwards the signal", async () => {
    const stub = installFetchStub(() => ok(projectProvidersFixture(PROJECT_ALPHA_ID)))
    const controller = new AbortController()

    const providers = await getProjectProviders(PROJECT_ALPHA_ID, controller.signal)

    expect(stub.requests[0]?.url).toBe(`/api/v1/projects/${PROJECT_ALPHA_ID}/providers`)
    expect(stub.requests[0]?.signal).toBe(controller.signal)
    expect(providers).toHaveLength(8)
  })

  it("maps wire ids to UI ids and catalog names and keeps only known operations", () => {
    const providers = decodeProjectProviders(
      projectProvidersFixture(PROJECT_ALPHA_ID, [
        projectProviderType("you"),
        { ...projectProviderType("brave"), effective_operations: ["search", "answer"] },
      ])
    )

    expect(providers).toEqual([
      {
        id: "youcom",
        name: "You.com",
        available: true,
        enabled: true,
        effectiveOperations: ["search", "fetch"],
      },
      {
        id: "brave",
        name: "Brave Search",
        available: true,
        enabled: true,
        effectiveOperations: ["search"],
      },
    ])
  })

  it("drops rows without a provider type and rejects a payload without a list", () => {
    expect(decodeProjectProviders({ providers: [{}, null, projectProviderType("exa")] })).toHaveLength(1)
    expect(() => decodeProjectProviders({})).toThrow()
  })

  it("filters the view by effective operation", () => {
    const providers = decodeProjectProviders(
      projectProvidersFixture(PROJECT_ALPHA_ID, [
        projectProviderType("brave"),
        projectProviderType("exa"),
        projectProviderType("tavily", []),
      ])
    )
    expect(providersForOperation(providers, "search").map((p) => p.id)).toEqual(["brave", "exa"])
    expect(providersForOperation(providers, "fetch").map((p) => p.id)).toEqual(["exa"])
  })
})
