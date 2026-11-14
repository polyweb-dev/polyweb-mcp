import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import type { ProjectOrder } from "@/domains/routing"
import type { ProjectPool, ProviderOwner } from "@/domains/projects"
import type { ProviderTypeView } from "@/domains/providers"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import type { ProjectProvidersController } from "../model/useProjectProvidersController"
import { ProjectProvidersContent } from "./ProjectProvidersContent"

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), toast: vi.fn() }))

vi.mock("@/domains/routing", () => ({ getProjectOrder: mocks.get, putProjectOrder: mocks.put }))
vi.mock("@/shared/notifications/useNotifications", () => ({ useNotifications: () => ({ showToast: mocks.toast }) }))

/**
 * TASK-000063 composition: ProjectProvidersContent derives `ownerContact`
 * through the shared `identityDetailLabel(ownerEntry)` and hands it to the
 * real ProviderOrderSection, so the empty-order Ask line carries the display
 * name with the email for disambiguation instead of the bare email.
 */
function emptyOrder(): ProjectOrder {
  const operation = { strategy: "lowest_cost" as const, providers: [], hasSavedCustom: false, notAllowed: [] }
  return { revision: 1, search: { ...operation }, fetch: { ...operation } }
}

function servingProvider(): ProviderTypeView {
  return {
    providerType: "tavily",
    name: "Tavily",
    keyless: false,
    capability: ["search", "fetch"],
    killSwitch: false,
    systemEnabledOperations: ["search", "fetch"],
    credentials: [],
    bindings: [],
    effectiveOperations: ["search", "fetch"],
  }
}

function servingPool(): ProjectPool {
  return {
    pool_id: "pool-1",
    label: "Tavily pool",
    provider_type: "tavily",
    key_label: "Team Tavily",
    owner: { user_id: "u1" },
    rate: { limit: 60, window_seconds: 60 },
    budget: null,
    budget_used: 0,
    operations: ["search", "fetch"],
  }
}

function ready<T>(data: T): ScopedResource<T> {
  return { status: "ready", data, reload: vi.fn() }
}

function renderContent(owner: ProviderOwner | null) {
  const controller: ProjectProvidersController = {
    view: ready({ providers: [servingProvider()] }),
    reloadAll: vi.fn(),
  }
  render(
    <MemoryRouter>
      <ProjectProvidersContent
        projectId="project"
        revision={0}
        controller={controller}
        owner={ready(owner)}
        pools={ready([servingPool()])}
        missing={[]}
        isOwner={false}
        canConfigure
        canEditSystem={false}
        reload={vi.fn()}
        add={vi.fn()}
        edit={vi.fn()}
        unassign={vi.fn()}
        changeOperation={vi.fn()}
        operationPending={false}
      />
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.get.mockResolvedValue(emptyOrder())
})

describe("ProjectProvidersContent owner contact wiring", () => {
  it("wires the owner display name into the empty order Ask line, without an email", async () => {
    renderContent({ user_id: "u1", username: "ada", first_name: "Ada", last_name: "Lovelace" })

    expect(await screen.findByText(/Ask Ada Lovelace to allow Search/)).toBeInTheDocument()
    expect(screen.queryByText(/@/)).not.toBeInTheDocument()
  })

  it("asks the generic provider owner, never an email, for a nameless owner payload", async () => {
    renderContent({ user_id: "u1", email: "lead@example.com" } as ProviderOwner)

    expect(await screen.findByText(/Ask the provider owner to allow Search/)).toBeInTheDocument()
    expect(screen.queryByText(/lead@example\.com/)).not.toBeInTheDocument()
  })
})
