import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { apiKeyFixture } from "@/test/accessFixtures"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ApiKeysTable } from "./ApiKeysTable"

const CREATOR = "11111111-1111-4111-8111-111111111111"

function controllerStub(overrides: Partial<ProjectApiKeysController> = {}): ProjectApiKeysController {
  return {
    keys: { status: "ready", data: [], reload: vi.fn(async () => []) },
    emailsByUserId: null,
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
    expect(within(table).getByText("This project has no API keys yet.")).toBeInTheDocument()
  })

  it("renders every column, newest first, with the creator email", () => {
    const keys = [
      apiKeyFixture({ id: "a", label: "Older", created_at: "2026-09-01T00:00:00Z", expires_at: null }),
      apiKeyFixture({ id: "b", label: "Newer", created_at: "2026-10-01T00:00:00Z", scopes: ["fetch.execute"], created_by: CREATOR }),
    ]
    render(
      <ApiKeysTable
        keys={keys}
        controller={controllerStub({ emailsByUserId: new Map([[CREATOR, "lead@example.com"]]) })}
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

  it("hides Rotate for an archived project and for an already-rotated key", () => {
    const keys = [
      apiKeyFixture({ id: "old", label: "Old" }),
      apiKeyFixture({ id: "new", label: "New", rotated_from_id: "old", created_at: "2026-10-09T00:00:00Z" }),
    ]
    const { unmount } = render(<ApiKeysTable keys={keys} controller={controllerStub()} archived={false} />)
    expect(screen.queryByRole("button", { name: "Rotate Old" })).toBeNull()
    expect(screen.getByRole("button", { name: "Rotate New" })).toBeInTheDocument()
    unmount()

    render(<ApiKeysTable keys={keys} controller={controllerStub()} archived />)
    expect(screen.queryByRole("button", { name: /^Rotate/ })).toBeNull()
    expect(screen.getByRole("button", { name: "Revoke New" })).toBeInTheDocument()
  })
})
