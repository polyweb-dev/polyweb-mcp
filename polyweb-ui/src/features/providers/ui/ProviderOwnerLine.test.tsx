import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import type { ProviderOwner } from "@/domains/projects"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { ProviderOwnerLine } from "./ProviderOwnerLine"

const transfer = vi.hoisted(() => vi.fn())
vi.mock("@/domains/projects/api/providerOwnerApi", () => ({ transferProviderOwner: transfer }))

function owner(data: ProviderOwner | null): ScopedResource<ProviderOwner | null> {
  return { status: "ready", data, reload: vi.fn() }
}

beforeEach(() => { transfer.mockReset() })

describe("ProviderOwnerLine", () => {
  it("lets an admin claim an unowned project after confirmation", async () => {
    transfer.mockResolvedValue({ user_id: "me", email: "me@example.com", unassigned_pools: [] })
    const onClaimed = vi.fn()
    render(<ProviderOwnerLine owner={owner(null)} projectId="p1" accountId="me" isAdmin canConfigure onClaimed={onClaimed} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Claim provider ownership" }))
    expect(transfer).not.toHaveBeenCalled()
    const dialog = screen.getByRole("dialog", { name: "Claim provider ownership" })
    await user.click(within(dialog).getByRole("button", { name: "Claim provider ownership" }))
    expect(transfer).toHaveBeenCalledExactlyOnceWith("p1", "me")
    expect(onClaimed).toHaveBeenCalledOnce()
  })

  it("tells a developer to ask an admin when there is no owner", () => {
    render(<ProviderOwnerLine owner={owner(null)} projectId="p1" accountId="me" isAdmin={false} canConfigure={false} onClaimed={vi.fn()} />)
    expect(screen.getByText(/This project has no provider owner/)).toHaveTextContent("Ask a project admin")
    expect(screen.queryByRole("button", { name: "Claim provider ownership" })).toBeNull()
  })

  it("offers project admins a transfer action", () => {
    render(<MemoryRouter><ProviderOwnerLine owner={owner({ user_id: "me", email: "me@example.com" })} projectId="p1" accountId="me" isAdmin canConfigure onClaimed={vi.fn()} /></MemoryRouter>)
    expect(screen.getByRole("link", { name: "Transfer ownership" })).toHaveAttribute("href", "/p/p1/members")
  })

  it("shows the owner full name primary with the email kept for contact", () => {
    render(
      <MemoryRouter>
        <ProviderOwnerLine
          owner={owner({ user_id: "u1", email: "ada@example.com", username: "ada", first_name: "Ada", last_name: "Lovelace" })}
          projectId="p1"
          accountId="me"
          isAdmin
          canConfigure
          onClaimed={vi.fn()}
        />
      </MemoryRouter>
    )

    const note = screen.getByRole("note")
    expect(note).toHaveTextContent("Provider owner: Ada Lovelace")
    expect(note).toHaveAttribute("title", "Ada Lovelace (ada@example.com)")
    expect(note).not.toHaveTextContent("(you)")
    expect(screen.getByText(/Only the provider owner can add or remove capacity/)).toHaveTextContent(
      "Ask Ada Lovelace (ada@example.com)"
    )
  })

  it("marks the caller with the username fallback and keeps the email secondary", () => {
    render(
      <MemoryRouter>
        <ProviderOwnerLine
          owner={owner({ user_id: "me", email: "ops@example.com", username: "ops-lead" })}
          projectId="p1"
          accountId="me"
          isAdmin
          canConfigure
          onClaimed={vi.fn()}
        />
      </MemoryRouter>
    )

    const note = screen.getByRole("note")
    expect(note).toHaveTextContent("Provider owner: ops-lead (you)")
    expect(note).toHaveAttribute("title", "ops-lead (ops@example.com)")
  })

  it("shows the email alone without a title for a legacy owner payload", () => {
    render(
      <MemoryRouter>
        <ProviderOwnerLine
          owner={owner({ user_id: "u1", email: "lead@example.com" })}
          projectId="p1"
          accountId="me"
          isAdmin={false}
          canConfigure={false}
          onClaimed={vi.fn()}
        />
      </MemoryRouter>
    )

    const note = screen.getByRole("note")
    expect(note).toHaveTextContent("Provider owner: lead@example.com")
    expect(note).not.toHaveAttribute("title")
  })
})
