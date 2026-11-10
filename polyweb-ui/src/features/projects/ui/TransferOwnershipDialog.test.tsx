import { afterEach, expect, it, vi } from "vitest"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { TransferOwnershipDialog } from "./TransferOwnershipDialog"

const admins = [
  { project_id: "p1", user_id: "old", email: "old@example.com", status: "active" as const, roles: ["project_admin"], role: "admin" as const, permissions: 33023, provider_owner: true, account_active: true, version: 1 },
  { project_id: "p1", user_id: "new", email: "new@example.com", status: "active" as const, roles: ["project_admin"], role: "admin" as const, permissions: 15, provider_owner: false, account_active: true, version: 1 },
]
afterEach(() => vi.unstubAllGlobals())

it("names pools affected by transfer and sends the selected admin", async () => {
  const stub = installFetchStub((request) => request.method === "GET"
    ? ok([{ pool_id: "pool1", label: "Search pool", provider_type: "brave", key_label: "Key",
      owner: { user_id: "old", email: "old@example.com" }, rate: { limit: 10, window_seconds: 60 },
      budget: null, budget_used: 0, operations: ["search"] },
    { pool_id: "pool2", label: "Alpha pool", provider_type: "exa", key_label: "Key",
      owner: { user_id: "old", email: "old@example.com" }, rate: { limit: 10, window_seconds: 60 },
      budget: null, budget_used: 0, operations: ["search"] }])
    : ok({ user_id: "new", email: "new@example.com", unassigned_pools: [{ pool_id: "pool1", label: "Search pool" }] }))
  const saved = vi.fn()
  render(<TransferOwnershipDialog projectId="p1" projectName="Project" members={admins} ownerId="old" onClose={vi.fn()} onSaved={saved} />)
  expect(await screen.findByText("Brave Search")).toBeInTheDocument()
  expect(screen.getByTestId("provider-logo-brave")).toBeInTheDocument()
  expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Brave Search", "Exa"])
  expect(screen.getByText("These providers stop until new@example.com adds capacity:")).toBeInTheDocument()
  expect(screen.queryByText(/Your pools no longer serve this project/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Transfer ownership" }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(stub.requests[1]?.body).toEqual({ user_id: "new" })
})

it("does not offer transfer when no other active admin exists", async () => {
  installFetchStub(() => ok([]))
  render(<TransferOwnershipDialog projectId="p1" projectName="Project" members={[admins[0]!]} ownerId="old" onClose={vi.fn()} onSaved={vi.fn()} />)
  expect(screen.getByText("Make another member a project admin first")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Transfer ownership" })).toBeNull()
  await act(async () => {})
})

it("excludes an inactive account from transfer recipients", async () => {
  installFetchStub(() => ok([]))
  render(<TransferOwnershipDialog projectId="p1" projectName="Project"
    members={[admins[0]!, { ...admins[1]!, account_active: false }]} ownerId="old" onClose={vi.fn()} onSaved={vi.fn()} />)
  expect(screen.getByText(/make another member a project admin first/i)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Transfer ownership" })).toBeNull()
  await act(async () => {})
})

it("disables transfer when the pool endpoint is not available", async () => {
  installFetchStub(() => err(404, null))
  render(<TransferOwnershipDialog projectId="p1" projectName="Project" members={admins} ownerId="old" onClose={vi.fn()} onSaved={vi.fn()} />)
  expect(await screen.findByRole("alert")).toHaveTextContent("This action is not available yet")
  expect(screen.getByRole("button", { name: "Transfer ownership" })).toBeDisabled()
})

it("lists recipients and confirms with the display name and email fallback", async () => {
  installFetchStub(() => ok([]))
  const named = { ...admins[1]!, username: "newbie", first_name: "New", last_name: "Member" }
  render(<TransferOwnershipDialog projectId="p1" projectName="Project" members={[admins[0]!, named]} ownerId="old" onClose={vi.fn()} onSaved={vi.fn()} />)
  expect(await screen.findByRole("combobox", { name: "New provider owner" })).toHaveTextContent(
    "New Member"
  )
  expect(screen.getAllByText("New Member (new@example.com)", { exact: false })).toHaveLength(2)
  expect(screen.getByText(/becomes the provider owner of/)).toBeInTheDocument()
  await act(async () => {})
})
