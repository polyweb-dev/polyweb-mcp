import { afterEach, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { MemberPermissionsDialog } from "./MemberPermissionsDialog"

const member = {
  project_id: "p1", user_id: "u1", email: "dev@example.com", status: "active" as const,
  roles: ["project_member"], role: "developer" as const, permissions: 15, provider_owner: false, account_active: true, version: 1,
}
afterEach(() => vi.unstubAllGlobals())

it("saves individual switches and retains the selected bit mask", async () => {
  const stub = installFetchStub(() => ok({ ...member, permissions: 79 }))
  const saved = vi.fn()
  render(<MemberPermissionsDialog projectId="p1" member={member} onClose={vi.fn()} onSaved={saved} />)
  const user = userEvent.setup()
  await user.click(screen.getByRole("switch", { name: "Change provider order" }))
  await user.click(screen.getByRole("button", { name: "Save permissions" }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(stub.requests[0]?.body).toEqual({ permissions: 79 })
})

it("shows a calm message when the endpoint does not exist", async () => {
  installFetchStub(() => err(404, null))
  render(<MemberPermissionsDialog projectId="p1" member={member} onClose={vi.fn()} onSaved={vi.fn()} />)
  const user = userEvent.setup()
  await user.click(screen.getByRole("switch", { name: "Fetch pages" }))
  await user.click(screen.getByRole("button", { name: "Save permissions" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("This action is not available yet")
  expect(screen.getByTestId("permissions-scroll")).not.toContainElement(screen.getByRole("alert"))
})

it("keeps all admin permission switches on and disabled", () => {
  render(<MemberPermissionsDialog projectId="p1" member={{ ...member, roles: ["project_admin"], role: "admin" }} onClose={vi.fn()} onSaved={vi.fn()} />)
  for (const control of screen.getAllByRole("switch")) {
    expect(control).toBeChecked()
    expect(control).toBeDisabled()
  }
})

it("counts the same enabled switches as the table, including Base access", async () => {
  render(<MemberPermissionsDialog projectId="p1" member={member} onClose={vi.fn()} onSaved={vi.fn()} />)
  expect(screen.getAllByRole("switch")).toHaveLength(9)
  expect(screen.getAllByRole("switch", { checked: true })).toHaveLength(5)
  expect(screen.getByRole("status")).toHaveTextContent("5 of 9 permissions")
  await userEvent.click(screen.getByRole("switch", { name: "Manage API keys" }))
  expect(screen.getByRole("status")).toHaveTextContent("6 of 9 permissions")
})

it("keeps Save enabled and closes an unchanged draft without a request", async () => {
  const stub = installFetchStub(() => ok(member))
  const close = vi.fn()
  render(<MemberPermissionsDialog projectId="p1" member={member} onClose={close} onSaved={vi.fn()} />)
  expect(screen.getByRole("button", { name: "Save permissions" })).toBeEnabled()
  await userEvent.click(screen.getByRole("button", { name: "Save permissions" }))
  expect(close).toHaveBeenCalledOnce()
  expect(stub.requests).toHaveLength(0)
})

it("shows progress and prevents duplicate saves while pending", async () => {
  let finish!: (response: Response) => void
  const stub = installFetchStub(() => new Promise<Response>((resolve) => { finish = resolve }))
  const saved = vi.fn()
  render(<MemberPermissionsDialog projectId="p1" member={member} onClose={vi.fn()} onSaved={saved} />)
  const user = userEvent.setup()
  await user.click(screen.getByRole("switch", { name: "Fetch pages" }))
  const save = screen.getByRole("button", { name: "Save permissions" })
  await user.click(save)
  expect(save).toBeDisabled()
  expect(save).toHaveAttribute("aria-busy", "true")
  expect(save).toHaveTextContent("Saving…")
  expect(screen.getByRole("status")).toHaveTextContent("4 of 9 permissions")
  await user.click(save)
  expect(stub.requests).toHaveLength(1)
  finish(ok({ ...member, permissions: 13 }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
})
