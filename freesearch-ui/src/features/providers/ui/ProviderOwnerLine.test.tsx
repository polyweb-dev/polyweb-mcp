import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import type { ProviderOwner } from "@/domains/projects"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { ProviderOwnerLine } from "./ProviderOwnerLine"

const transfer = vi.hoisted(() => vi.fn())
vi.mock("@/domains/projects", () => ({ transferProviderOwner: transfer }))

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
    await user.click(screen.getByRole("button", { name: "Become provider owner" }))
    expect(transfer).not.toHaveBeenCalled()
    const dialog = screen.getByRole("dialog", { name: "Become provider owner" })
    await user.click(within(dialog).getByRole("button", { name: "Become provider owner" }))
    expect(transfer).toHaveBeenCalledExactlyOnceWith("p1", "me")
    expect(onClaimed).toHaveBeenCalledOnce()
  })

  it("tells a developer to ask an admin when there is no owner", () => {
    render(<ProviderOwnerLine owner={owner(null)} projectId="p1" accountId="me" isAdmin={false} canConfigure={false} onClaimed={vi.fn()} />)
    expect(screen.getByText(/This project has no provider owner/)).toHaveTextContent("Ask a project admin")
    expect(screen.queryByRole("button", { name: "Become provider owner" })).toBeNull()
  })

  it("offers project admins a transfer action", () => {
    render(<MemoryRouter><ProviderOwnerLine owner={owner({ user_id: "me", email: "me@example.com" })} projectId="p1" accountId="me" isAdmin canConfigure onClaimed={vi.fn()} /></MemoryRouter>)
    expect(screen.getByRole("link", { name: "Transfer ownership" })).toHaveAttribute("href", "/p/p1/members")
  })
})
