import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { apiKeyFixture } from "@/test/accessFixtures"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ApiKeysTable } from "./ApiKeysTable"

const CREATOR = "11111111-1111-4111-8111-111111111111"
const OTHER_CREATOR = "22222222-2222-4222-8222-222222222222"

function controllerStub(overrides: Partial<ProjectApiKeysController> = {}): ProjectApiKeysController {
  return {
    keys: { status: "ready", data: [], reload: vi.fn(async () => []) },
    identitiesByUserId: null,
    pending: false,
    message: null,
    showMessage: vi.fn(),
    revealedKey: null,
    dismissReveal: vi.fn(),
    issue: vi.fn(async () => true),
    rotate: vi.fn(async () => true),
    revoke: vi.fn(async () => {}),
    confirmingRevokeId: null,
    requestRevoke: vi.fn(),
    rotatingKey: null,
    openRotate: vi.fn(),
    ...overrides,
  }
}

describe("ApiKeysTable", () => {
  it("keeps the labelled table with an empty-state row when there are no keys", () => {
    render(<ApiKeysTable keys={[]} controller={controllerStub()} archived={false} />)
    const table = screen.getByRole("table", { name: "API keys" })
    expect(within(table).getByText("No keys yet")).toBeInTheDocument()
  })

  it("shows the creator display name when identities carry a saved profile", () => {
    const keys = [apiKeyFixture({ id: "a", label: "Named", created_by: CREATOR })]
    render(
      <ApiKeysTable
        keys={keys}
        controller={controllerStub({
          identitiesByUserId: new Map([
            [CREATOR, { email: "ada@example.com", username: "ada", first_name: "Ada", last_name: "Lovelace" }],
          ]),
        })}
        archived={false}
      />
    )
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument()
  })

  it("disambiguates two creators who share one personal name by email title", () => {
    const keys = [
      apiKeyFixture({ id: "a", label: "First", created_at: "2026-09-01T00:00:00Z", created_by: CREATOR }),
      apiKeyFixture({ id: "b", label: "Second", created_at: "2026-10-01T00:00:00Z", created_by: OTHER_CREATOR }),
    ]
    render(
      <ApiKeysTable
        keys={keys}
        controller={controllerStub({
          identitiesByUserId: new Map([
            [CREATOR, { email: "ada-one@example.com", first_name: "Ada", last_name: "Lovelace" }],
            [OTHER_CREATOR, { email: "ada-two@example.com", first_name: "Ada", last_name: "Lovelace" }],
          ]),
        })}
        archived={false}
      />
    )
    expect(screen.getAllByText("Ada Lovelace")).toHaveLength(2)
    const rows = screen.getAllByRole("row")
    expect(within(rows[1]).getByText("Ada Lovelace")).toHaveAttribute(
      "title",
      "Ada Lovelace (ada-two@example.com)"
    )
    expect(within(rows[2]).getByText("Ada Lovelace")).toHaveAttribute(
      "title",
      "Ada Lovelace (ada-one@example.com)"
    )
  })

  it("keeps each creator contact tied to its key row under the Key label", () => {
    const keys = [
      apiKeyFixture({ id: "a", label: "First", created_at: "2026-09-01T00:00:00Z", created_by: CREATOR }),
      apiKeyFixture({ id: "b", label: "Second", created_at: "2026-10-01T00:00:00Z", created_by: OTHER_CREATOR }),
    ]
    render(
      <ApiKeysTable
        keys={keys}
        controller={controllerStub({
          identitiesByUserId: new Map([
            [CREATOR, { email: "ada-one@example.com", first_name: "Ada", last_name: "Lovelace" }],
            [OTHER_CREATOR, { email: "ada-two@example.com", first_name: "Ada", last_name: "Lovelace" }],
          ]),
        })}
        archived={false}
      />
    )
    // Newest first: the Second/ada-two key sorts above the First/ada-one key,
    // and each Key cell carries only its own creator contact title.
    const rows = screen.getAllByRole("row")
    const [newerCell, olderCell] = [within(rows[1]).getAllByRole("cell")[0]!, within(rows[2]).getAllByRole("cell")[0]!]
    expect(within(newerCell).getByText("Second")).toBeInTheDocument()
    expect(
      within(newerCell).getByTitle("Ada Lovelace (ada-two@example.com)")
    ).toHaveTextContent("Ada Lovelace")
    expect(newerCell.textContent).not.toContain("ada-one@example.com")
    expect(within(olderCell).getByText("First")).toBeInTheDocument()
    expect(
      within(olderCell).getByTitle("Ada Lovelace (ada-one@example.com)")
    ).toHaveTextContent("Ada Lovelace")
    expect(olderCell.textContent).not.toContain("ada-two@example.com")
  })

  it("renders every column, newest first, with the creator email", () => {
    const keys = [
      apiKeyFixture({ id: "a", label: "Older", created_at: "2026-09-01T00:00:00Z", expires_at: null }),
      apiKeyFixture({ id: "b", label: "Newer", created_at: "2026-10-01T00:00:00Z", scopes: ["fetch.execute"], created_by: CREATOR }),
    ]
    render(
      <ApiKeysTable
        keys={keys}
        controller={controllerStub({ identitiesByUserId: new Map([[CREATOR, { email: "lead@example.com" }]]) })}
        archived={false}
      />
    )
    const rows = screen.getAllByRole("row")
    expect(rows[1]).toHaveTextContent("Newer")
    expect(rows[1]).toHaveTextContent("fs_live_abcd")
    expect(rows[1]).toHaveTextContent(/fetch/i)
    expect(rows[1]).toHaveTextContent("lead@example.com")
    expect(rows[1]).toHaveTextContent("Never")
    expect(rows[2]).toHaveTextContent("Older")
    expect(rows[2]).toHaveTextContent(/search.*fetch/i)
    expect(rows[2]).toHaveTextContent("No expiration")
  })

  it("hides Rotate for an archived project and for an already-rotated key", async () => {
    const user = userEvent.setup()
    const keys = [
      apiKeyFixture({ id: "old", label: "Old" }),
      apiKeyFixture({ id: "new", label: "New", rotated_from_id: "old", created_at: "2026-10-09T00:00:00Z" }),
    ]
    const { unmount } = render(<ApiKeysTable keys={keys} controller={controllerStub()} archived={false} />)

    await user.click(screen.getByRole("button", { name: "Actions for Old" }))
    expect(screen.queryByRole("button", { name: "Rotate key" })).toBeNull()
    expect(screen.getByRole("button", { name: "Revoke key" })).toBeInTheDocument()
    await user.keyboard("{Escape}")

    await user.click(screen.getByRole("button", { name: "Actions for New" }))
    expect(screen.getByRole("button", { name: "Rotate key" })).toBeInTheDocument()
    await user.keyboard("{Escape}")
    unmount()

    render(<ApiKeysTable keys={keys} controller={controllerStub()} archived />)
    await user.click(screen.getByRole("button", { name: "Actions for New" }))
    expect(screen.queryByRole("button", { name: "Rotate key" })).toBeNull()
    expect(screen.getByRole("button", { name: "Revoke key" })).toBeInTheDocument()
  })
})
